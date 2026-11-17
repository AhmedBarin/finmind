"""Fakes for Stock Q&A unit tests: in-memory tools and a scripted LLM."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.explanation.llm import ExplanationLLMError
from app.explanation.stock_qa.schemas import ToolResult
from app.explanation.snapshots import snapshot_summary

TODAY = date(2026, 11, 17)
DATA_DATE = date(2026, 11, 16)


def make_snapshot(ticker: str = "COMI.CA", day: date = DATA_DATE, **overrides: Any) -> SimpleNamespace:
    values = {
        "ticker": ticker,
        "date": day,
        "data_quality_status": "valid",
        "rsi": 56.2347,
        "sma_20": 81.456,
        "sma_50": 78.9,
        "atr": 2.31,
        "setup_score": 64.5,
        "regime": "trending",
        "risk_label": "medium",
        "quality_flags": [],
        "indicators": {"rsi14": 56.2347, "adx14": 27.4},
        "scores": {"trend": 71.0},
        "input_data": {"source_window": [{"Close": 999.99}]},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTools:
    """Duck-typed stand-in for StockQATools backed by a dict of snapshots."""

    def __init__(self, snapshots: dict[str, SimpleNamespace]) -> None:
        self.snapshots = snapshots
        self.calls: list[str] = []

    async def get_technical_snapshot(self, ticker, on=None):
        self.calls.append("get_technical_snapshot")
        snap = self.snapshots.get(ticker)
        if snap is None:
            return ToolResult(tool="get_technical_snapshot", ticker=ticker, found=False)
        data = snapshot_summary(snap) | {"indicators": snap.indicators, "scores": snap.scores}
        return ToolResult(tool="get_technical_snapshot", ticker=ticker, data_date=snap.date, data=data)

    async def get_snapshot_history(self, ticker, start, end):
        self.calls.append("get_snapshot_history")
        snap = self.snapshots[ticker]
        return ToolResult(
            tool="get_snapshot_history",
            ticker=ticker,
            data_date=snap.date,
            data={"snapshots": [snapshot_summary(snap)]},
        )

    async def get_price_history(self, ticker, period, end=None):
        self.calls.append("get_price_history")
        snap = self.snapshots.get(ticker)
        if snap is None:
            return ToolResult(tool="get_price_history", ticker=ticker, found=False, data={"prices": []})
        prices = [{"date": snap.date.isoformat(), "close": 82.15, "adj_close": 82.15, "volume": 1250000}]
        return ToolResult(tool="get_price_history", ticker=ticker, data_date=snap.date, data={"prices": prices})

    async def compare_snapshots(self, tickers, on=None):
        self.calls.append("compare_snapshots")
        rows = [snapshot_summary(self.snapshots[t]) for t in tickers if t in self.snapshots]
        return ToolResult(tool="compare_snapshots", found=bool(rows), data={"snapshots": rows})

    async def get_indicator_glossary(self, name):
        self.calls.append("get_indicator_glossary")
        return ToolResult(tool="get_indicator_glossary", data={"key": name})


class ScriptedGenerator:
    """Returns queued replies; an Exception in the queue is raised instead."""

    model_name = "fake-model"

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


def draft(answer: str, facts: list[dict] | None = None, limitations: list[str] | None = None) -> dict:
    return {"answer_ar": answer, "facts": facts or [], "limitations_ar": limitations or []}


GOOD_ANSWER = "بتاريخ 2026-11-16 بلغ مؤشر القوة النسبية لسهم COMI.CA نحو 56.2، والسهم في حالة اتجاه واضح."
GOOD_FACTS = [{"ticker": "COMI.CA", "field": "rsi", "value": 56.2347, "data_date": "2026-11-16"}]


@pytest.fixture
def generation_error() -> Exception:
    return ExplanationLLMError("boom")
