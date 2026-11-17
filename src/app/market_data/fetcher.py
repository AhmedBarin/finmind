"""Yahoo Finance adapter for daily market prices."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import os
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REQUIRED_COLUMNS = {
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
}
_ACTION_COLUMNS = {"Dividends", "Stock Splits"}
_VALID_PERIODS = {"max", "1mo"}
EODHD_BASE_URL = "https://eodhd.com/api"
CAIRO_TZ = ZoneInfo("Africa/Cairo")
logger = logging.getLogger(__name__)


class _EodhdSettings(BaseSettings):
    api_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EODHD_API_TOKEN", "EODHD_TOKEN"),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@dataclass(frozen=True)
class FetchedPriceHistory:
    ticker: str
    source: str
    prices: pd.DataFrame


class PriceFetcher(Protocol):
    async def fetch(
        self,
        ticker: str,
        *,
        period: str,
    ) -> FetchedPriceHistory: ...


HistoryCall = Callable[..., pd.DataFrame]


class YahooFinanceFetcher:
    """Fetch daily Yahoo Finance history without blocking the event loop."""

    source = "yahoo_finance"

    def __init__(self, history_call: HistoryCall | None = None) -> None:
        # Injectable so unit tests can use a fake without making network calls.
        self._history_call = history_call

    @staticmethod
    def _yahoo_symbol(ticker: str) -> str:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        return normalized if normalized.endswith(".CA") else f"{normalized}.CA"

    def _fetch_sync(self, symbol: str, period: str) -> pd.DataFrame:
        history_call = self._history_call

        if history_call is None:
            try:
                import yfinance as yf
            except ImportError as exc:
                raise RuntimeError(
                    "Yahoo Finance fetching requires the yfinance dependency."
                ) from exc

            history_call = lambda ticker, **kwargs: yf.Ticker(ticker).history(
                **kwargs
            )

        return history_call(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=False,
            actions=True,
        )

    async def fetch(
        self,
        ticker: str,
        *,
        period: str,
    ) -> FetchedPriceHistory:
        if period not in _VALID_PERIODS:
            raise ValueError(f"period must be one of {sorted(_VALID_PERIODS)}")

        symbol = self._yahoo_symbol(ticker)
        prices = await asyncio.to_thread(self._fetch_sync, symbol, period)

        if not isinstance(prices, pd.DataFrame):
            raise TypeError("Yahoo Finance history must return a pandas DataFrame")

        # A no-trading-day response is an empty result, not a fetch error.
        if prices.empty:
            return FetchedPriceHistory(
                ticker=symbol,
                source=self.source,
                prices=prices.copy(),
            )

        missing = _REQUIRED_COLUMNS - set(prices.columns)
        if missing:
            raise ValueError(
                f"Yahoo Finance response is missing columns: {sorted(missing)}"
            )

        normalized = prices.copy()

        # Keep action values for raw storage/auditing; they are omitted later
        # when creating indicator inputs.
        for column in _ACTION_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = 0.0

        index = pd.DatetimeIndex(normalized.index)
        if index.tz is not None:
            index = index.tz_localize(None)

        normalized.index = index.normalize()
        normalized.index.name = "date"

        if normalized.index.has_duplicates:
            raise ValueError(f"Yahoo Finance returned duplicate dates for {symbol}")

        normalized = normalized.sort_index()

        for column in _REQUIRED_COLUMNS | _ACTION_COLUMNS:
            normalized[column] = pd.to_numeric(
                normalized[column],
                errors="raise",
            )

        return FetchedPriceHistory(
            ticker=symbol,
            source=self.source,
            prices=normalized,
        )


class EodhdFetcher:
    """EODHD fallback provider, including dividend and split action data."""

    source = "eodhd"

    def __init__(
        self,
        token: str | None = None,
        *,
        symbol_map: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token or _EodhdSettings().api_token or os.getenv(
            "EODHD_API_TOKEN"
        ) or os.getenv("EODHD_TOKEN")
        self._symbol_map = {
            key.strip().upper(): value.strip().upper()
            for key, value in (symbol_map or {}).items()
        }
        self._client = client

    def _eodhd_symbol(self, ticker: str) -> str:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        if normalized in self._symbol_map:
            return self._symbol_map[normalized]
        if normalized.endswith(".EGX"):
            return normalized
        code = normalized[:-3] if normalized.endswith(".CA") else normalized
        return f"{code}.EGX"

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        symbol: str,
        *,
        params: dict[str, str],
    ) -> list[dict[str, object]]:
        query = {"api_token": self._token or "", "fmt": "json", **params}
        try:
            response = await client.get(
                f"{EODHD_BASE_URL}/{endpoint}/{symbol}",
                params=query,
            )
        except httpx.HTTPError as exc:
            # Do not chain HTTP errors: their URL can contain the API token.
            raise RuntimeError(
                f"EODHD {endpoint} request failed ({type(exc).__name__})"
            ) from None

        if response.is_error:
            raise RuntimeError(f"EODHD {endpoint} returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError(f"EODHD {endpoint} returned invalid JSON") from None
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise RuntimeError(f"EODHD {endpoint} returned an unexpected response")
        return payload

    async def fetch(
        self,
        ticker: str,
        *,
        period: str,
    ) -> FetchedPriceHistory:
        if period not in _VALID_PERIODS:
            raise ValueError(f"period must be one of {sorted(_VALID_PERIODS)}")
        if not self._token:
            raise RuntimeError(
                "EODHD fallback requires EODHD_API_TOKEN (or EODHD_TOKEN)."
            )

        symbol = self._eodhd_symbol(ticker)
        params: dict[str, str] = {"period": "d", "order": "a"}
        action_params: dict[str, str] = {}
        if period == "1mo":
            start_date = (
                datetime.now(CAIRO_TZ).date() - timedelta(days=31)
            ).isoformat()
            params["from"] = start_date
            action_params["from"] = start_date

        if self._client is None:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._fetch_with_client(
                    client, ticker, symbol, params, action_params
                )
        return await self._fetch_with_client(
            self._client, ticker, symbol, params, action_params
        )

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        ticker: str,
        symbol: str,
        params: dict[str, str],
        action_params: dict[str, str],
    ) -> FetchedPriceHistory:
        prices, dividends, splits = await asyncio.gather(
            self._request_json(client, "eod", symbol, params=params),
            self._request_json(client, "div", symbol, params=action_params),
            self._request_json(client, "splits", symbol, params=action_params),
        )
        if not prices:
            return FetchedPriceHistory(
                ticker=self._yahoo_ticker(ticker),
                source=self.source,
                prices=pd.DataFrame(),
            )

        dividend_by_date = {
            pd.Timestamp(item["date"]).normalize(): item.get(
                "unadjustedValue", item.get("value", 0)
            )
            for item in dividends
            if item.get("date") is not None
        }
        split_by_date = {
            pd.Timestamp(item["date"]).normalize(): _split_ratio(item.get("split"))
            for item in splits
            if item.get("date") is not None
        }

        rows: list[dict[str, object]] = []
        dates: list[pd.Timestamp] = []
        required = {"date", "open", "high", "low", "close", "adjusted_close", "volume"}
        for item in prices:
            missing = required - item.keys()
            if missing:
                raise RuntimeError(
                    f"EODHD eod response is missing fields: {sorted(missing)}"
                )
            day = pd.Timestamp(item["date"]).normalize()
            dates.append(day)
            rows.append(
                {
                    "Open": item["open"],
                    "High": item["high"],
                    "Low": item["low"],
                    "Close": item["close"],
                    "Adj Close": item["adjusted_close"],
                    "Volume": item["volume"],
                    "Dividends": dividend_by_date.get(day, 0),
                    "Stock Splits": split_by_date.get(day, 0),
                }
            )

        frame = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="date"))
        if frame.index.has_duplicates:
            raise RuntimeError(f"EODHD returned duplicate dates for {symbol}")
        frame = frame.sort_index()
        return FetchedPriceHistory(
            ticker=self._yahoo_ticker(ticker),
            source=self.source,
            prices=frame,
        )

    @staticmethod
    def _yahoo_ticker(ticker: str) -> str:
        normalized = ticker.strip().upper()
        return normalized if normalized.endswith(".CA") else f"{normalized}.CA"


def _split_ratio(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        new_shares, old_shares = str(value).split("/", maxsplit=1)
        old_ratio = float(old_shares)
        if old_ratio == 0:
            raise ValueError("split denominator must not be zero")
        return float(new_shares) / old_ratio
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid EODHD split ratio: {value!r}") from exc


class FallbackPriceFetcher:
    """Try the primary provider, then the fallback on errors or empty data."""

    def __init__(self, primary: PriceFetcher, fallback: PriceFetcher) -> None:
        self._primary = primary
        self._fallback = fallback

    async def fetch(
        self,
        ticker: str,
        *,
        period: str,
    ) -> FetchedPriceHistory:
        primary_failure: str | None = None
        try:
            primary_result = await self._primary.fetch(ticker, period=period)
        except Exception as primary_error:
            primary_failure = type(primary_error).__name__
            logger.warning(
                "Primary price provider failed for %s (%s); trying fallback.",
                ticker,
                type(primary_error).__name__,
            )
        else:
            if not primary_result.prices.empty:
                return primary_result
            primary_failure = "empty response"
            logger.info("Primary provider returned no rows for %s; trying fallback.", ticker)

        try:
            fallback_result = await self._fallback.fetch(ticker, period=period)
        except Exception as fallback_error:
            raise RuntimeError(
                "All configured price providers failed "
                f"(primary={primary_failure}, "
                f"fallback={type(fallback_error).__name__})."
            ) from None
        if fallback_result.prices.empty and primary_failure != "empty response":
            raise RuntimeError(
                "Primary provider failed and fallback returned no price rows."
            ) from None
        return fallback_result
