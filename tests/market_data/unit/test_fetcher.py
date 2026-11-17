from __future__ import annotations

import pandas as pd
import httpx
import pytest

from app.market_data.fetcher import (
    EodhdFetcher,
    FallbackPriceFetcher,
    FetchedPriceHistory,
    YahooFinanceFetcher,
    _split_ratio,
)


def _history(index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    if index is None:
        index = pd.DatetimeIndex(["2026-01-04 12:30:00"])
    return pd.DataFrame(
        {
            "Open": [10.0] * len(index),
            "High": [11.0] * len(index),
            "Low": [9.0] * len(index),
            "Close": [10.5] * len(index),
            "Adj Close": [10.0] * len(index),
            "Volume": [1000] * len(index),
        },
        index=index,
    )


@pytest.mark.asyncio
async def test_fetcher_calls_yahoo_with_raw_daily_prices_and_normalizes_dates() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_history(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append((symbol, kwargs))
        index = pd.DatetimeIndex(["2026-01-04 12:30:00"], tz="Africa/Cairo")
        return _history(index)

    result = await YahooFinanceFetcher(fake_history).fetch("comi", period="1mo")

    assert result.ticker == "COMI.CA"
    assert result.source == "yahoo_finance"
    assert result.prices.index.name == "date"
    assert result.prices.index[0] == pd.Timestamp("2026-01-04")
    assert result.prices.index.tz is None
    assert result.prices.loc[result.prices.index[0], "Dividends"] == 0.0
    assert result.prices.loc[result.prices.index[0], "Stock Splits"] == 0.0
    assert calls == [
        (
            "COMI.CA",
            {
                "period": "1mo",
                "interval": "1d",
                "auto_adjust": False,
                "actions": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_fetcher_rejects_unsupported_period() -> None:
    with pytest.raises(ValueError, match="period"):
        await YahooFinanceFetcher(lambda *_args, **_kwargs: _history()).fetch(
            "COMI.CA", period="5y"
        )


@pytest.mark.asyncio
async def test_fetcher_accepts_empty_history_as_no_new_session() -> None:
    result = await YahooFinanceFetcher(lambda *_args, **_kwargs: pd.DataFrame()).fetch(
        "COMI.CA", period="1mo"
    )

    assert result.prices.empty


@pytest.mark.asyncio
async def test_fetcher_rejects_duplicate_dates() -> None:
    duplicated = _history(pd.DatetimeIndex(["2026-01-04", "2026-01-04"]))
    duplicated.loc[duplicated.index[1], "Close"] = 12.0

    with pytest.raises(ValueError, match="duplicate dates"):
        await YahooFinanceFetcher(
            lambda *_args, **_kwargs: duplicated
        ).fetch("COMI.CA", period="max")


@pytest.mark.asyncio
async def test_fetcher_rejects_missing_required_columns() -> None:
    incomplete = _history().drop(columns=["Adj Close"])

    with pytest.raises(ValueError, match="Adj Close"):
        await YahooFinanceFetcher(
            lambda *_args, **_kwargs: incomplete
        ).fetch("COMI.CA", period="max")


@pytest.mark.asyncio
async def test_eodhd_fetcher_maps_prices_actions_and_egx_symbol() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/api/eod/" in str(request.url):
            return httpx.Response(
                200,
                json=[
                    {
                        "date": "2026-01-04",
                        "open": 10.0,
                        "high": 12.0,
                        "low": 9.0,
                        "close": 11.0,
                        "adjusted_close": 5.5,
                        "volume": 1000,
                    }
                ],
            )
        if "/api/div/" in str(request.url):
            return httpx.Response(
                200,
                json=[{"date": "2026-01-04", "unadjustedValue": 0.25}],
            )
        if "/api/splits/" in str(request.url):
            return httpx.Response(
                200,
                json=[{"date": "2026-01-04", "split": "3.000000/2.000000"}],
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await EodhdFetcher("test-token", client=client).fetch(
            "COMI.CA", period="max"
        )

    row = result.prices.iloc[0]
    assert result.ticker == "COMI.CA"
    assert result.source == "eodhd"
    assert result.prices.index[0] == pd.Timestamp("2026-01-04")
    assert row["Adj Close"] == 5.5
    assert row["Dividends"] == 0.25
    assert row["Stock Splits"] == 1.5
    assert len(requests) == 3
    assert {request.url.path for request in requests} == {
        "/api/eod/COMI.EGX",
        "/api/div/COMI.EGX",
        "/api/splits/COMI.EGX",
    }
    assert all(request.url.params["api_token"] == "test-token" for request in requests)


@pytest.mark.asyncio
async def test_eodhd_fetcher_supports_symbol_override() -> None:
    seen_symbols: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        seen_symbols.add(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await EodhdFetcher(
            "test-token",
            symbol_map={"COMI.CA": "COMI.CAIRO"},
            client=client,
        ).fetch("COMI.CA", period="1mo")

    assert result.prices.empty
    assert seen_symbols == {"COMI.CAIRO"}


@pytest.mark.asyncio
async def test_fallback_fetcher_uses_eodhd_if_yahoo_fails() -> None:
    class FailingFetcher:
        async def fetch(self, _ticker: str, *, period: str) -> FetchedPriceHistory:
            raise OSError("network unavailable")

    class BackupFetcher:
        async def fetch(self, ticker: str, *, period: str) -> FetchedPriceHistory:
            assert ticker == "COMI.CA"
            assert period == "max"
            return FetchedPriceHistory("COMI.CA", "eodhd", _history())

    result = await FallbackPriceFetcher(FailingFetcher(), BackupFetcher()).fetch(
        "COMI.CA", period="max"
    )

    assert result.source == "eodhd"


def test_split_ratio_supports_non_integer_split_ratios() -> None:
    assert _split_ratio("7.000000/2.000000") == 3.5
