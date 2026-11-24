"""Allowlisted, read-only data tools for Stock Q&A."""

from __future__ import annotations

import inspect
import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.explanation.glossary import get_indicator_glossary
from app.market_data.calendar import count_egx_sessions, get_verified_egx_calendar
from app.market_data.config import EGX_TRADING_WEEKDAYS
from app.market_data.repository import get_stock_price_history
from app.technical_analysis.repository import (
    compare_snapshots as repository_compare_snapshots,
    get_snapshot_by_date,
    get_snapshot_history,
)
from app.technical_analysis.schemas import StockPriceRead, TechnicalSnapshotRead


ALLOWED_STOCK_QA_TOOLS = frozenset(
    {
        "get_technical_snapshot",
        "get_snapshot_history",
        "get_price_history",
        "compare_snapshots",
        "get_indicator_glossary",
    }
)
SUPPORTED_PRICE_PERIODS = ("1w", "1mo", "3mo", "6mo", "1y")
DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 500
MAX_TOOL_RESULT_BYTES = 48_000
_CAIRO = ZoneInfo("Africa/Cairo")


class StockQAToolResult(BaseModel):
    """Bounded, provenance-bearing output shared by the five data tools."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    status: Literal["available", "not_found", "stale", "partial", "unavailable"]
    tickers: list[str] = Field(default_factory=list, max_length=5)
    data_date: date | None = None
    freshness_status: Literal["fresh", "stale", "unavailable", "not_applicable"]
    trading_days_old: int | None = Field(default=None, ge=0)
    payload: Any = None
    limitations: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False


def _today_cairo() -> date:
    return datetime.now(_CAIRO).date()


def _calendar_months_before(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(absolute_month, 12)
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _period_start(period: str, end_date: date) -> date:
    normalized = period.strip().casefold()
    period_months = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12}
    if normalized == "1w":
        return end_date - timedelta(days=7)
    if normalized in period_months:
        return _calendar_months_before(end_date, period_months[normalized])
    raise ValueError(
        f"unsupported period {period!r}; use one of {', '.join(SUPPORTED_PRICE_PERIODS)}"
    )


async def _freshness(
    session: AsyncSession,
    data_date: date | None,
    *,
    as_of_date: date,
) -> tuple[Literal["fresh", "stale", "unavailable", "not_applicable"], int | None, list[str]]:
    if data_date is None:
        return "not_applicable", None, []
    if data_date > as_of_date:
        return "unavailable", None, ["بيانات بتاريخ مستقبلي؛ تعذر التحقق من حداثتها."]
    first_check_date = data_date + timedelta(days=1)
    if first_check_date > as_of_date:
        return "fresh", 0, []

    possible_sessions = [
        first_check_date + timedelta(days=offset)
        for offset in range((as_of_date - first_check_date).days + 1)
        if (first_check_date + timedelta(days=offset)).weekday() in EGX_TRADING_WEEKDAYS
    ]
    if not possible_sessions:
        return "fresh", 0, []

    calendar = await get_verified_egx_calendar(
        session, possible_sessions[0], possible_sessions[-1]
    )
    if calendar is None:
        return "unavailable", None, [
            "تعذر التحقق من حداثة البيانات: تغطية تقويم عطلات البورصة المصرية غير مكتملة لهذه الفترة."
        ]
    age = count_egx_sessions(first_check_date, as_of_date, calendar.holidays)
    if age > 2:
        return "stale", age, [
            f"البيانات أقدم من الحد المسموح: مرّت {age} جلسات تداول مصرية منذ تاريخ البيانات؛ يُرجى التعامل معها بحذر."
        ]
    return "fresh", age, []


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    """Serialize useful snapshot fields while omitting bulky source history."""
    data = TechnicalSnapshotRead.model_validate(snapshot).model_dump(mode="json")
    input_data = data.get("input_data") or {}
    data["input_data"] = {
        key: input_data[key]
        for key in ("as_of_date", "history_session_count", "calculation_window_sessions")
        if key in input_data
    }
    return data


def _bounded_result(result: StockQAToolResult) -> dict[str, Any]:
    data = result.model_dump(mode="json")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
        return data

    payload = data.get("payload")
    rows_key = next(
        (key for key in ("snapshots", "prices") if isinstance(payload, dict) and isinstance(payload.get(key), list)),
        None,
    )
    if rows_key is not None:
        rows = payload[rows_key]
        data["truncated"] = True
        data["limitations"].append("قُلّصت النتائج للالتزام بحد حجم البيانات.")
        while rows:
            if rows_key == "snapshots":
                rows.pop()
            else:
                rows.pop(0)
            data["payload"][rows_key] = rows
            data["payload"]["count"] = len(rows)
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
                return data
    return StockQAToolResult(
        tool=result.tool,
        status="partial",
        tickers=result.tickers,
        data_date=result.data_date,
        freshness_status=result.freshness_status,
        trading_days_old=result.trading_days_old,
        payload=None,
        limitations=[*result.limitations, "تعذر إرجاع البيانات ضمن حد حجم الأداة."],
        truncated=True,
    ).model_dump(mode="json")


async def _result_for_snapshot(
    session: AsyncSession,
    *,
    tool: str,
    ticker: str,
    snapshot: Any | None,
    as_of_date: date,
) -> dict[str, Any]:
    normalized_ticker = ticker.strip().upper()
    if snapshot is None:
        return StockQAToolResult(
            tool=tool,
            status="not_found",
            tickers=[normalized_ticker],
            freshness_status="not_applicable",
            limitations=["لم يُعثر على لقطة فنية مطابقة للطلب."],
        ).model_dump(mode="json")
    freshness, age, limitations = await _freshness(
        session,
        snapshot.date,
        as_of_date=as_of_date,
    )
    status = "stale" if freshness == "stale" else "partial" if freshness == "unavailable" else "available"
    if snapshot.data_quality_status == "stale" and freshness != "stale":
        status = "partial"
        limitations.append(
            "محرك التحليل الفني سجّل اللقطة كقديمة؛ لم يؤكد تقويم العطلات الرسمي هذا التصنيف الحالي."
        )
    return _bounded_result(
        StockQAToolResult(
            tool=tool,
            status=status,
            tickers=[normalized_ticker],
            data_date=snapshot.date,
            freshness_status=freshness,
            trading_days_old=age,
            payload=_snapshot_payload(snapshot),
            limitations=limitations,
        )
    )


async def get_technical_snapshot_data(
    session: AsyncSession,
    ticker: str,
    snapshot_date: date,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Get one stored technical snapshot for an exact trading date."""
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    normalized = ticker.strip().upper()
    snapshot = await get_snapshot_by_date(session, normalized, snapshot_date)
    return await _result_for_snapshot(
        session,
        tool="get_technical_snapshot",
        ticker=normalized,
        snapshot=snapshot,
        as_of_date=as_of_date or _today_cairo(),
    )


async def get_snapshot_history_data(
    session: AsyncSession,
    ticker: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = DEFAULT_ROW_LIMIT,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    if not 1 <= limit <= MAX_ROW_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_ROW_LIMIT}")
    normalized_ticker = ticker.strip().upper()
    effective_as_of = as_of_date or _today_cairo()
    effective_to = to_date or effective_as_of
    if effective_to > effective_as_of:
        raise ValueError("to_date must not be in the future")
    if from_date is not None and from_date > effective_to:
        raise ValueError("from_date must be on or before to_date")
    snapshots = await get_snapshot_history(
        session,
        normalized_ticker,
        start_date=from_date,
        end_date=effective_to,
        limit=limit,
    )
    if not snapshots:
        return StockQAToolResult(
            tool="get_snapshot_history",
            status="not_found",
            tickers=[normalized_ticker],
            freshness_status="not_applicable",
            payload={"from_date": from_date, "to_date": effective_to, "count": 0, "snapshots": []},
            limitations=["لا توجد لقطات فنية ضمن الفترة المطلوبة."],
        ).model_dump(mode="json")

    newest_date = max(item.date for item in snapshots)
    oldest_date = min(item.date for item in snapshots)
    freshness, age, limitations = await _freshness(
        session, newest_date, as_of_date=effective_as_of
    )
    status = "stale" if freshness == "stale" else "partial" if freshness == "unavailable" else "available"
    if any(
        item.data_quality_status == "stale"
        for item in snapshots
        if item.date == newest_date
    ) and freshness != "stale":
        status = "partial"
        limitations.append(
            "محرك التحليل الفني سجّل أحدث لقطة كقديمة؛ لم يؤكد تقويم العطلات الرسمي هذا التصنيف الحالي."
        )
    return _bounded_result(
        StockQAToolResult(
            tool="get_snapshot_history",
            status=status,
            tickers=[normalized_ticker],
            data_date=newest_date,
            freshness_status=freshness,
            trading_days_old=age,
            payload={
                "from_date": from_date,
                "to_date": effective_to,
                "count": len(snapshots),
                "oldest_date": oldest_date,
                "snapshots": [_snapshot_payload(item) for item in snapshots],
            },
            limitations=limitations,
        )
    )


async def get_price_history_data(
    session: AsyncSession,
    ticker: str,
    period: str,
    limit: int = DEFAULT_ROW_LIMIT,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    if not 1 <= limit <= MAX_ROW_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_ROW_LIMIT}")
    normalized_ticker = ticker.strip().upper()
    effective_as_of = as_of_date or _today_cairo()
    start_date = _period_start(period, effective_as_of)
    prices = await get_stock_price_history(
        session,
        normalized_ticker,
        start_date=start_date,
        end_date=effective_as_of,
        limit=limit,
    )
    if not prices:
        return StockQAToolResult(
            tool="get_price_history",
            status="not_found",
            tickers=[normalized_ticker],
            freshness_status="not_applicable",
            payload={"period": period, "from_date": start_date, "to_date": effective_as_of, "count": 0, "prices": []},
            limitations=["لا توجد أسعار محفوظة ضمن فترة البحث المطلوبة."],
        ).model_dump(mode="json")

    newest_date = max(item.date for item in prices)
    freshness, age, limitations = await _freshness(
        session, newest_date, as_of_date=effective_as_of
    )
    status = "stale" if freshness == "stale" else "partial" if freshness == "unavailable" else "available"
    return _bounded_result(
        StockQAToolResult(
            tool="get_price_history",
            status=status,
            tickers=[normalized_ticker],
            data_date=newest_date,
            freshness_status=freshness,
            trading_days_old=age,
            payload={
                "period": period,
                "from_date": start_date,
                "to_date": effective_as_of,
                "count": len(prices),
                "prices": [StockPriceRead.model_validate(item).model_dump(mode="json") for item in prices],
            },
            limitations=limitations,
        )
    )


async def compare_snapshots_data(
    session: AsyncSession,
    ticker: str,
    first_date: date,
    second_date: date,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    normalized_ticker = ticker.strip().upper()
    first, second = await repository_compare_snapshots(
        session, normalized_ticker, first_date, second_date
    )
    if first is None and second is None:
        return StockQAToolResult(
            tool="compare_snapshots",
            status="not_found",
            tickers=[normalized_ticker],
            freshness_status="not_applicable",
            payload={"first_date": first_date, "second_date": second_date, "first": None, "second": None},
            limitations=["لم يُعثر على لقطات فنية لأي من التاريخين المطلوبين."],
        ).model_dump(mode="json")

    effective_as_of = as_of_date or _today_cairo()
    present = [item for item in (first, second) if item is not None]
    data_date = max(item.date for item in present)
    freshness, age, limitations = await _freshness(
        session, data_date, as_of_date=effective_as_of
    )
    status = "partial" if first is None or second is None else "available"
    if freshness == "stale":
        status = "stale"
    elif freshness == "unavailable":
        status = "partial"
    if any(item.data_quality_status == "stale" for item in present) and freshness != "stale":
        status = "partial"
        limitations.append(
            "محرك التحليل الفني سجّل لقطة المقارنة كقديمة؛ لم يؤكد تقويم العطلات الرسمي هذا التصنيف الحالي."
        )
    return _bounded_result(
        StockQAToolResult(
            tool="compare_snapshots",
            status=status,
            tickers=[normalized_ticker],
            data_date=data_date,
            freshness_status=freshness,
            trading_days_old=age,
            payload={
                "first_date": first_date,
                "second_date": second_date,
                "first": _snapshot_payload(first) if first is not None else None,
                "second": _snapshot_payload(second) if second is not None else None,
            },
            limitations=limitations + (["إحدى اللقطتين غير متاحة."] if first is None or second is None else []),
        )
    )


def get_indicator_glossary_data(name: str) -> dict[str, Any]:
    definition = get_indicator_glossary(name)
    if definition is None:
        return {
            "tool": "get_indicator_glossary",
            "status": "not_found",
            "name": name,
            "limitations": ["المصطلح غير موجود في قاموس المؤشرات المتاح."],
        }
    return {
        "tool": "get_indicator_glossary",
        "status": "available",
        "definition": definition.model_dump(mode="json"),
        "limitations": [],
    }


def build_stock_qa_tools(*, session: AsyncSession) -> list[Any]:
    """Build the five and only five allowlisted LangChain data tools."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise RuntimeError(
            "LangChain dependencies are not installed; run `uv sync`."
        ) from exc

    async def get_technical_snapshot(ticker: str, snapshot_date: date) -> dict[str, Any]:
        return await get_technical_snapshot_data(session, ticker, snapshot_date)

    async def get_snapshot_history(
        ticker: str,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = DEFAULT_ROW_LIMIT,
    ) -> dict[str, Any]:
        return await get_snapshot_history_data(session, ticker, from_date, to_date, limit)

    async def get_price_history(
        ticker: str,
        period: Literal["1w", "1mo", "3mo", "6mo", "1y"],
        limit: int = DEFAULT_ROW_LIMIT,
    ) -> dict[str, Any]:
        return await get_price_history_data(session, ticker, period, limit)

    async def compare_snapshots(
        ticker: str, first_date: date, second_date: date
    ) -> dict[str, Any]:
        return await compare_snapshots_data(session, ticker, first_date, second_date)

    definitions = [
        ("get_technical_snapshot", get_technical_snapshot, "Read one stored EGX technical snapshot for an exact trading date."),
        ("get_snapshot_history", get_snapshot_history, "Read bounded stored EGX snapshot history for one ticker."),
        ("get_price_history", get_price_history, f"Read stored prices for a lookback period: {', '.join(SUPPORTED_PRICE_PERIODS)}."),
        ("compare_snapshots", compare_snapshots, "Compare one ticker's stored snapshots across two dates."),
        ("get_indicator_glossary", get_indicator_glossary_data, "Look up a bilingual technical-indicator definition."),
    ]
    tools: list[Any] = []
    for name, fn, description in definitions:
        if name not in ALLOWED_STOCK_QA_TOOLS:
            continue
        kwargs = {"coroutine": fn} if inspect.iscoroutinefunction(fn) else {"func": fn}
        tools.append(
            StructuredTool.from_function(
                **kwargs,
                name=name,
                description=description,
            )
        )
    return tools
