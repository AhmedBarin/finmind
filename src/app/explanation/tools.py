"""Read-only snapshot tools for the Explanation Agent (REQ-032, PLAN-014).

Each tool conforms to the ``ExplanationTool`` protocol and returns
deterministic, source-backed data with ``data_date`` and freshness metadata.
All tools are strictly read-only: they query existing repositories and never
mutate state.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indicator glossary — deterministic, no DB access
# ---------------------------------------------------------------------------

_INDICATOR_GLOSSARY: dict[str, dict[str, str]] = {
    "RSI": {
        "name_ar": "مؤشر القوة النسبية",
        "description_ar": "يقيس سرعة وتغير حركة الأسعار، قراءة فوق 70 تشير لتشبع شرائي وأقل من 30 تشير لتشبع بيعي.",
        "description_en": "Measures speed and change of price movements; above 70 is overbought, below 30 is oversold.",
        "range": "0–100",
    },
    "SMA_20": {
        "name_ar": "المتوسط المتحرك البسيط (20 يوم)",
        "description_ar": "متوسط سعر الإغلاق لآخر 20 جلسة تداول، يُستخدم لتحديد الاتجاه قصير المدى.",
        "description_en": "Simple moving average of closing prices over 20 trading sessions; identifies short-term trend.",
        "range": "price-level",
    },
    "SMA_50": {
        "name_ar": "المتوسط المتحرك البسيط (50 يوم)",
        "description_ar": "متوسط سعر الإغلاق لآخر 50 جلسة تداول، يُستخدم لتحديد الاتجاه متوسط المدى.",
        "description_en": "Simple moving average of closing prices over 50 trading sessions; identifies medium-term trend.",
        "range": "price-level",
    },
    "ATR": {
        "name_ar": "متوسط المدى الحقيقي",
        "description_ar": "يقيس تقلبات السعر اليومية، قيمة أعلى تعني تقلبات أكبر.",
        "description_en": "Average True Range measures daily price volatility; higher values indicate higher volatility.",
        "range": "≥ 0",
    },
    "SETUP_SCORE": {
        "name_ar": "درجة الإعداد الفني",
        "description_ar": "درجة مركبة من 0 إلى 100 تقيّم قوة الإعداد الفني بناءً على عدة مؤشرات.",
        "description_en": "Composite score from 0–100 evaluating technical setup strength from multiple indicators.",
        "range": "0–100",
    },
    "REGIME": {
        "name_ar": "نظام السوق",
        "description_ar": "يصنف حالة السوق الحالية (صاعد، هابط، أو عرضي).",
        "description_en": "Classifies the current market regime (bullish, bearish, or sideways).",
        "range": "categorical",
    },
    "RISK_LABEL": {
        "name_ar": "تصنيف المخاطر",
        "description_ar": "تصنيف مستوى مخاطر السهم بناءً على تقلبات الأسعار.",
        "description_en": "Volatility-based risk classification for the stock.",
        "range": "categorical",
    },
}


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _freshness_seconds(dt: datetime | date | None) -> int | None:
    """Seconds since ``dt``; returns None when ``dt`` is unavailable."""
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time(), tzinfo=UTC)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = _now_utc() - dt
    return max(0, int(delta.total_seconds()))


def _snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    """Convert a TechnicalSnapshotRead to a serialisable dict."""
    return {
        "ticker": snapshot.ticker,
        "date": snapshot.date.isoformat() if snapshot.date else None,
        "rsi": snapshot.rsi,
        "sma_20": snapshot.sma_20,
        "sma_50": snapshot.sma_50,
        "atr": snapshot.atr,
        "setup_score": snapshot.setup_score,
        "regime": snapshot.regime,
        "risk_label": snapshot.risk_label,
        "data_quality_status": snapshot.data_quality_status,
    }


def _price_to_dict(price: Any) -> dict[str, Any]:
    """Convert a StockPriceRead to a serialisable dict."""
    return {
        "ticker": price.ticker,
        "date": price.date.isoformat() if price.date else None,
        "open": float(price.adj_open) if price.adj_open is not None else None,
        "high": float(price.adj_high) if price.adj_high is not None else None,
        "low": float(price.adj_low) if price.adj_low is not None else None,
        "close": float(price.adj_close) if price.adj_close is not None else None,
        "volume": price.volume,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════


class TechnicalSnapshotTool:
    """Fetch the latest technical snapshot for a ticker (read-only)."""

    name = "technical_snapshot"

    def __init__(self, snapshot_repo: Any) -> None:
        self._repo = snapshot_repo

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ticker: str = arguments["ticker"].strip().upper()
        try:
            snapshot = await self._repo.get_latest_snapshot(ticker)
        except Exception:
            logger.exception("technical_snapshot failed for %s", ticker)
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "unavailable",
                "error": "Failed to retrieve technical snapshot.",
            }

        if snapshot is None:
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "not_found",
            }

        return {
            "tool": self.name,
            "ticker": ticker,
            "data_date": snapshot.date.isoformat() if snapshot.date else None,
            "freshness_seconds": _freshness_seconds(snapshot.date),
            "status": "ok" if snapshot.data_quality_status == "valid" else "stale",
            "snapshot": _snapshot_to_dict(snapshot),
        }


class SnapshotHistoryTool:
    """Fetch historical technical snapshots for a ticker (read-only)."""

    name = "snapshot_history"

    def __init__(self, snapshot_repo: Any) -> None:
        self._repo = snapshot_repo

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ticker: str = arguments["ticker"].strip().upper()
        days: int = min(int(arguments.get("days", 30)), 90)
        try:
            snapshots = await self._repo.get_snapshot_history(ticker, days=days)
        except Exception:
            logger.exception("snapshot_history failed for %s", ticker)
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "unavailable",
                "error": "Failed to retrieve snapshot history.",
            }

        if not snapshots:
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "not_found",
                "count": 0,
                "snapshots": [],
            }

        latest_date = max(s.date for s in snapshots if s.date)
        return {
            "tool": self.name,
            "ticker": ticker,
            "data_date": latest_date.isoformat() if latest_date else None,
            "freshness_seconds": _freshness_seconds(latest_date),
            "status": "ok",
            "count": len(snapshots),
            "snapshots": [_snapshot_to_dict(s) for s in snapshots],
        }


class PriceHistoryTool:
    """Fetch historical OHLCV price data for a ticker (read-only)."""

    name = "price_history"

    def __init__(self, price_repo: Any) -> None:
        self._repo = price_repo

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ticker: str = arguments["ticker"].strip().upper()
        days: int = min(int(arguments.get("days", 30)), 90)
        try:
            prices = await self._repo.get_price_history(ticker, days=days)
        except Exception:
            logger.exception("price_history failed for %s", ticker)
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "unavailable",
                "error": "Failed to retrieve price history.",
            }

        if not prices:
            return {
                "tool": self.name,
                "ticker": ticker,
                "data_date": None,
                "freshness_seconds": None,
                "status": "not_found",
                "count": 0,
                "prices": [],
            }

        latest_date = max(p.date for p in prices if p.date)
        return {
            "tool": self.name,
            "ticker": ticker,
            "data_date": latest_date.isoformat() if latest_date else None,
            "freshness_seconds": _freshness_seconds(latest_date),
            "status": "ok",
            "count": len(prices),
            "prices": [_price_to_dict(p) for p in prices],
        }


class SnapshotComparisonTool:
    """Compare latest snapshots across multiple EGX tickers (read-only)."""

    name = "snapshot_comparison"

    def __init__(self, snapshot_repo: Any) -> None:
        self._repo = snapshot_repo

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_tickers: list[str] = arguments.get("tickers", [])
        tickers = [t.strip().upper() for t in raw_tickers if t.strip()][:5]

        results: list[dict[str, Any]] = []
        latest_date: date | None = None
        any_found = False

        for ticker in tickers:
            try:
                snapshot = await self._repo.get_latest_snapshot(ticker)
            except Exception:
                logger.exception("snapshot_comparison failed for %s", ticker)
                results.append({"ticker": ticker, "status": "unavailable"})
                continue

            if snapshot is None:
                results.append({"ticker": ticker, "status": "not_found"})
                continue

            any_found = True
            if snapshot.date and (latest_date is None or snapshot.date > latest_date):
                latest_date = snapshot.date
            results.append(
                {
                    "ticker": ticker,
                    "status": "ok"
                    if snapshot.data_quality_status == "valid"
                    else "stale",
                    "snapshot": _snapshot_to_dict(snapshot),
                }
            )

        return {
            "tool": self.name,
            "tickers": tickers,
            "data_date": latest_date.isoformat() if latest_date else None,
            "freshness_seconds": _freshness_seconds(latest_date),
            "status": "ok" if any_found else "not_found",
            "comparisons": results,
        }


class IndicatorGlossaryTool:
    """Return deterministic indicator definitions — no DB access."""

    name = "indicator_glossary"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "data_date": _now_utc().date().isoformat(),
            "freshness_seconds": 0,
            "status": "ok",
            "indicators": _INDICATOR_GLOSSARY,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Registry helper
# ═══════════════════════════════════════════════════════════════════════════


def build_default_tools(
    snapshot_repo: Any = None,
    price_repo: Any = None,
) -> list[Any]:
    """Build the standard 5 read-only tools.

    When repositories are ``None`` placeholder stubs are used (useful for
    testing without a database).
    """
    snapshot_repo = snapshot_repo or _StubSnapshotRepo()
    price_repo = price_repo or _StubPriceRepo()

    return [
        TechnicalSnapshotTool(snapshot_repo),
        SnapshotHistoryTool(snapshot_repo),
        PriceHistoryTool(price_repo),
        SnapshotComparisonTool(snapshot_repo),
        IndicatorGlossaryTool(),
    ]


# ── Stub repos for offline / test usage ──────────────────────────────────


class _StubSnapshotRepo:
    async def get_latest_snapshot(self, ticker: str) -> None:
        return None

    async def get_snapshot_history(self, ticker: str, *, days: int = 30) -> list:
        return []


class _StubPriceRepo:
    async def get_price_history(self, ticker: str, *, days: int = 30) -> list:
        return []
