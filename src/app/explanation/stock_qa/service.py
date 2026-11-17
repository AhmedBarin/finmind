"""Stock Q&A orchestration: route, gather, generate, validate, fall back.

Flow:
1. Split the question. Advice-seeking parts go to ``routed_to_recommendation``
   and are never answered here.
2. Call the read-only tools for each ticker. The code chooses the tools; the
   LLM never gets direct data access.
3. Ask the LLM for a draft, then validate it: schema, recommendation language,
   number grounding, ticker scope, fact dates, and the data date in the answer.
4. On failure retry once with the reasons; if it fails again (or no LLM is
   configured) answer with a template built only from stored values.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from app.explanation.stock_qa.generator import StockQAGenerationError, StockQAGenerator
from app.explanation.stock_qa.glossary import terms_in_question
from app.explanation.stock_qa.grounding import (
    INDICATOR_NAME_NUMBERS,
    collect_numbers,
    is_grounded,
    normalize_digits,
    ungrounded_numbers,
)
from app.explanation.stock_qa.language import find_recommendation_language, split_question
from app.explanation.stock_qa.prompt import PROMPT_VERSION, build_messages, retry_message
from app.explanation.stock_qa.schemas import (
    GenerationPath,
    StockQADraft,
    StockQAFact,
    StockQARequest,
    StockQAResponse,
    TickerFreshness,
    ToolName,
    ToolResult,
)
from app.explanation.stock_qa.tools import PERIOD_DAYS, StockQATools

logger = logging.getLogger(__name__)

DISCLAIMER_AR = (
    "هذه الإجابة وصف للبيانات المخزنة فقط، وليست توصية بالشراء أو البيع أو الاحتفاظ، "
    "ولا تضمن أي نتائج استثمارية."
)
ROUTED_ONLY_ANSWER_AR = (
    "سؤالك يطلب رأيًا استثماريًا، وهذا من اختصاص محرك التوصيات وليس من اختصاص "
    "الأسئلة الوصفية عن الأسهم."
)
ROUTED_NOTE_AR = "جزء من سؤالك يطلب رأيًا استثماريًا، وقد أُحيل إلى محرك التوصيات ولم تتم الإجابة عليه هنا."
NO_DATA_ANSWER_AR = "لا توجد بيانات فنية مخزنة للأسهم المطلوبة، لذلك لا يمكن الإجابة على السؤال حاليًا."
NO_LLM_NOTE_AR = "خدمة التوليد اللغوي غير متاحة حاليًا، لذا تُعرض القيم المخزنة كما هي."
FALLBACK_INTRO_AR = "تعذر إعداد إجابة مفصلة تستوفي شروط التحقق، لذا تُعرض القيم المخزنة كما هي."

_REGIME_AR = {"trending": "اتجاه واضح", "transition": "مرحلة انتقالية", "ranging": "تذبذب عرضي"}
_RISK_AR = {"low": "منخفض", "medium": "متوسط", "high": "مرتفع", "very_high": "مرتفع جدًا"}
_FALLBACK_NUMERIC_FIELDS = (
    ("rsi", "مؤشر القوة النسبية"),
    ("sma_20", "المتوسط المتحرك لعشرين جلسة"),
    ("sma_50", "المتوسط المتحرك لخمسين جلسة"),
    ("atr", "متوسط المدى الحقيقي"),
    ("setup_score", "درجة الإعداد الفني"),
)
_FALLBACK_LABEL_FIELDS = (
    ("regime", "حالة السوق", _REGIME_AR),
    ("risk_label", "تصنيف المخاطر", _RISK_AR),
)


@dataclass
class _Context:
    tickers: list[str]
    question: str
    results: list[ToolResult] = field(default_factory=list)
    snapshots: dict[str, ToolResult] = field(default_factory=dict)
    tools_used: list[ToolName] = field(default_factory=list)
    freshness: list[TickerFreshness] = field(default_factory=list)
    known_dates: dict[str, set[date]] = field(default_factory=dict)
    allowed_numbers: set[float] = field(default_factory=set)

    def record(self, result: ToolResult) -> ToolResult:
        self.results.append(result)
        if result.tool not in self.tools_used:
            self.tools_used.append(result.tool)
        return result

    @property
    def snapshot_dates(self) -> list[date]:
        return [r.data_date for r in self.snapshots.values() if r.found and r.data_date]

    @property
    def data_date(self) -> date | None:
        dates = self.snapshot_dates
        return min(dates) if dates else None


def _number_text(value: float) -> str:
    return format(abs(value), "f").rstrip("0").rstrip(".") or "0"


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


class StockQAService:
    def __init__(
        self,
        generator: StockQAGenerator | None,
        *,
        max_snapshot_age_days: int = 4,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._generator = generator
        self._max_age = timedelta(days=max_snapshot_age_days)
        self._today = today

    async def answer(self, tools: StockQATools, request: StockQARequest) -> StockQAResponse:
        descriptive, advice = split_question(request.question)
        if not descriptive:
            return self._log(
                StockQAResponse(
                    tickers=request.tickers,
                    data_date=None,
                    answer_ar=ROUTED_ONLY_ANSWER_AR,
                    facts=[],
                    limitations_ar=[],
                    disclaimer_ar=DISCLAIMER_AR,
                    freshness=[],
                    routed_to_recommendation=advice,
                    generation="routed_only",
                    tools_used=[],
                )
            )

        ctx = await self._gather(tools, request, "، ".join(descriptive))
        limitations = self._base_limitations(ctx, advice)
        base: dict[str, Any] = {
            "tickers": request.tickers,
            "data_date": ctx.data_date,
            "disclaimer_ar": DISCLAIMER_AR,
            "freshness": ctx.freshness,
            "routed_to_recommendation": advice,
            "tools_used": ctx.tools_used,
        }

        if ctx.data_date is None:
            return self._log(
                StockQAResponse(
                    **base,
                    answer_ar=NO_DATA_ANSWER_AR,
                    facts=[],
                    limitations_ar=limitations,
                    generation="no_data",
                )
            )
        if self._generator is None:
            return self._log(self._fallback(ctx, base, [*limitations, NO_LLM_NOTE_AR]))

        draft, path = await self._generate(ctx)
        if draft is None:
            return self._log(self._fallback(ctx, base, limitations))
        return self._log(
            StockQAResponse(
                **base,
                answer_ar=draft.answer_ar,
                facts=draft.facts,
                limitations_ar=_dedupe([*limitations, *draft.limitations_ar]),
                generation=path,
            )
        )

    # ── Tool gathering ────────────────────────────────────────────────

    async def _gather(
        self, tools: StockQATools, request: StockQARequest, question: str
    ) -> _Context:
        ctx = _Context(tickers=request.tickers, question=question)
        window = timedelta(days=PERIOD_DAYS[request.period])

        for ticker in request.tickers:
            snapshot = ctx.record(await tools.get_technical_snapshot(ticker, request.as_of))
            ctx.snapshots[ticker] = snapshot
            end = snapshot.data_date or request.as_of
            if snapshot.found and end is not None:
                ctx.record(await tools.get_snapshot_history(ticker, end - window, end))
            ctx.record(await tools.get_price_history(ticker, request.period, end=end))

        if len(request.tickers) > 1:
            ctx.record(await tools.compare_snapshots(request.tickers, request.as_of))
        for term in terms_in_question(question):
            ctx.record(await tools.get_indicator_glossary(term))

        ctx.freshness = [self._freshness(t, ctx.snapshots[t], request.as_of) for t in request.tickers]
        ctx.known_dates = self._known_dates(ctx)
        # Only tool output grounds a number. Numbers in the question are not
        # trusted: "RSI is 90, right?" must not let the model confirm 90.
        ctx.allowed_numbers = collect_numbers(
            [r.model_dump(mode="json") for r in ctx.results]
        )
        ctx.allowed_numbers |= INDICATOR_NAME_NUMBERS
        return ctx

    def _freshness(self, ticker: str, snapshot: ToolResult, as_of: date | None) -> TickerFreshness:
        if not snapshot.found or snapshot.data_date is None:
            return TickerFreshness(ticker=ticker, data_date=None, status="missing")
        quality = snapshot.data.get("data_quality_status")
        too_old = as_of is None and self._today() - snapshot.data_date > self._max_age
        return TickerFreshness(
            ticker=ticker,
            data_date=snapshot.data_date,
            status="stale" if quality == "stale" or too_old else "fresh",
            data_quality_status=quality,
        )

    @staticmethod
    def _known_dates(ctx: _Context) -> dict[str, set[date]]:
        known: dict[str, set[date]] = {t: set() for t in ctx.tickers}
        for result in ctx.results:
            rows: list[dict[str, Any]] = []
            if result.tool == "get_technical_snapshot" and result.found:
                rows = [result.data]
            else:
                rows = result.data.get("snapshots", []) or result.data.get("prices", [])
            for row in rows:
                ticker = row.get("ticker") or result.ticker
                raw = row.get("date")
                if ticker in known and raw:
                    known[ticker].add(date.fromisoformat(str(raw)))
        return known

    @staticmethod
    def _base_limitations(ctx: _Context, advice: list[str]) -> list[str]:
        notes: list[str] = []
        for item in ctx.freshness:
            if item.status == "missing":
                notes.append(f"لا توجد لقطة فنية مخزنة للسهم {item.ticker}.")
            elif item.status == "stale":
                notes.append(
                    f"بيانات السهم {item.ticker} تعود إلى {item.data_date.isoformat()} "
                    "وقد لا تعكس الوضع الحالي."
                )
            if item.data_quality_status not in (None, "valid", "stale"):
                notes.append(f"حالة جودة بيانات السهم {item.ticker}: {item.data_quality_status}.")
        if advice:
            notes.append(ROUTED_NOTE_AR)
        return notes

    # ── Generation and validation ─────────────────────────────────────

    async def _generate(self, ctx: _Context) -> tuple[StockQADraft | None, GenerationPath]:
        assert self._generator is not None
        messages = build_messages(
            question=ctx.question,
            tickers=ctx.tickers,
            tool_results=[r.model_dump(mode="json") for r in ctx.results],
            freshness=[f.model_dump(mode="json") for f in ctx.freshness],
        )
        for attempt in range(2):
            try:
                raw = await self._generator.complete(messages)
            except StockQAGenerationError as exc:
                logger.warning("stock_qa generation failed: %s", exc)
                return None, "fallback"
            try:
                draft = StockQADraft.model_validate_json(raw)
            except ValidationError as exc:
                issues = [
                    "Output did not match output_schema: "
                    + "; ".join(
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                        for e in exc.errors()[:5]
                    )
                ]
            else:
                issues = self.validate_draft(draft, ctx)
            if not issues:
                return draft, "llm" if attempt == 0 else "llm_retry"
            logger.info("stock_qa draft rejected (attempt %d): %d issue(s)", attempt + 1, len(issues))
            messages = [*messages, {"role": "assistant", "content": raw}, retry_message(issues)]
        return None, "fallback"

    def validate_draft(self, draft: StockQADraft, ctx: _Context) -> list[str]:
        issues: list[str] = []

        def check_text(text: str, where: str) -> None:
            hits = find_recommendation_language(text)
            if hits:
                issues.append(f"{where} contains recommendation language: {', '.join(hits)}")
            bad = ungrounded_numbers(text, ctx.allowed_numbers)
            if bad:
                issues.append(f"{where} has numbers not found in tool_results: {', '.join(bad)}")

        check_text(draft.answer_ar, "answer_ar")
        for note in draft.limitations_ar:
            check_text(note, "limitations_ar")

        for fact in draft.facts:
            ticker = fact.ticker.strip().upper()
            if ticker not in ctx.tickers:
                issues.append(f"facts cites ticker {fact.ticker} that was not requested")
                continue
            check_text(fact.field, "facts.field")
            if isinstance(fact.value, str):
                check_text(fact.value, "facts.value")
            elif not is_grounded(_number_text(fact.value), ctx.allowed_numbers):
                issues.append(f"facts value {fact.value} for {ticker}.{fact.field} is not in tool_results")
            if fact.data_date and fact.data_date not in ctx.known_dates.get(ticker, set()):
                issues.append(f"facts data_date {fact.data_date} for {ticker} is not in tool_results")

        answer = normalize_digits(draft.answer_ar)
        if not any(d.isoformat() in answer for d in ctx.snapshot_dates):
            issues.append("answer_ar must state the data date in the form YYYY-MM-DD")
        return _dedupe(issues)

    # ── Safe template ─────────────────────────────────────────────────

    @staticmethod
    def _fallback(ctx: _Context, base: dict[str, Any], limitations: list[str]) -> StockQAResponse:
        lines = [FALLBACK_INTRO_AR]
        facts: list[StockQAFact] = []
        for ticker in ctx.tickers:
            snapshot = ctx.snapshots[ticker]
            if not snapshot.found or snapshot.data_date is None:
                lines.append(f"لا توجد لقطة فنية مخزنة للسهم {ticker}.")
                continue
            data, day = snapshot.data, snapshot.data_date
            parts: list[str] = []
            for key, label in _FALLBACK_NUMERIC_FIELDS:
                value = data.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    parts.append(f"{label} {value:.2f}")
                    facts.append(StockQAFact(ticker=ticker, field=key, value=value, data_date=day))
            for key, label, names in _FALLBACK_LABEL_FIELDS:
                value = data.get(key)
                if value:
                    parts.append(f"{label} {names.get(value, value)}")
                    facts.append(StockQAFact(ticker=ticker, field=key, value=value, data_date=day))
            if parts:
                lines.append(f"بيانات {ticker} بتاريخ {day.isoformat()}: " + "، ".join(parts) + ".")
            else:
                lines.append(f"لا تتوفر قيم مؤشرات للسهم {ticker} بتاريخ {day.isoformat()}.")
        return StockQAResponse(
            **base,
            answer_ar="\n".join(lines),
            facts=facts,
            limitations_ar=_dedupe(limitations),
            generation="fallback",
        )

    def _log(self, response: StockQAResponse) -> StockQAResponse:
        logger.info(
            "stock_qa answered generation=%s tickers=%s prompt=%s model=%s",
            response.generation,
            ",".join(response.tickers),
            PROMPT_VERSION,
            getattr(self._generator, "model_name", None),
        )
        return response
