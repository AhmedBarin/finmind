"""Explain a monitoring alert without changing it (US-009).

The alert's facts (rule, observed value, threshold, timestamps, data date) are
copied into the response by code. The LLM only writes the Arabic text, which
is validated like Stock Q&A: no recommendation language, every number from
the alert or its snapshots, and the data date stated. One retry, then a
per-alert-type template built from the stored values.
"""

from __future__ import annotations

import logging
from typing import Any

from app.explanation.alerts.prompt import PROMPT_VERSION, build_messages
from app.explanation.alerts.schemas import (
    AlertExplanationDraft,
    AlertExplanationInput,
    AlertExplanationResponse,
    AlertKeyFactor,
    SourceRef,
)
from app.explanation.generation import dedupe, generate_validated, text_issues
from app.explanation.grounding import (
    INDICATOR_NAME_NUMBERS,
    collect_numbers,
    extract_numbers,
    is_grounded,
    normalize_digits,
    number_text,
)
from app.explanation.llm import ExplanationLLM
from app.explanation.snapshots import snapshot_summary
from app.technical_analysis.models import TechnicalSnapshot

logger = logging.getLogger(__name__)

DISCLAIMER_AR = (
    "هذا التفسير يصف سبب إطلاق التنبيه وفق البيانات المخزنة فقط، وليس توصية استثمارية "
    "ولا ضمانًا لأي نتائج."
)
NEWS_NOT_SEARCHED_AR = (
    "لم يتم البحث في الأخبار أو إفصاحات الشركة، لذلك سبب الحركة غير معروف من البيانات المتاحة."
)
NO_LLM_NOTE_AR = "خدمة التوليد اللغوي غير متاحة حاليًا، لذا يُعرض تفسير مبني على قيم التنبيه المخزنة."
TEMPLATE_RISK_AR = "التنبيه مبني على قراءة يوم واحد، وقد تتغير القراءة في الجلسات التالية."

RULE_LABELS_AR = {
    "rsi_threshold": "حد مؤشر القوة النسبية",
    "price_ma_cross": "تقاطع السعر مع المتوسط المتحرك",
    "volatility_threshold": "حد التقلب (نسبة متوسط المدى الحقيقي إلى السعر)",
    "score_change": "تغير الدرجة الفنية المركبة",
}


def _fmt(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return "غير متاح"


class AlertExplanationService:
    def __init__(self, llm: ExplanationLLM | None) -> None:
        self._llm = llm

    async def explain(
        self,
        inp: AlertExplanationInput,
        current: TechnicalSnapshot | None,
        previous: TechnicalSnapshot | None,
    ) -> AlertExplanationResponse:
        """Explain a validated alert (see ``AlertExplanationInput.from_alert``)."""
        current_data = snapshot_summary(current) if current is not None else None
        previous_data = snapshot_summary(previous) if previous is not None else None
        alert_data = inp.model_dump(mode="json", exclude={"alert_id"}) | {
            "triggered_rule": RULE_LABELS_AR[inp.alert_type]
        }

        allowed = collect_numbers([alert_data, current_data, previous_data]) | INDICATOR_NAME_NUMBERS
        limitations = self._base_limitations(inp, current, previous)
        base: dict[str, Any] = {
            "alert_id": inp.alert_id,
            "ticker": inp.ticker,
            "alert_type": inp.alert_type,
            "severity": inp.severity,
            "triggered_rule": RULE_LABELS_AR[inp.alert_type],
            "reason": inp.reason,
            "observed_value": inp.observed_value,
            "threshold_value": inp.threshold_value,
            "observed_at": inp.observed_at,
            "data_date": inp.data_date,
            "sources": self._sources(inp, current, previous),
            "disclaimer_ar": DISCLAIMER_AR,
        }

        if self._llm is None:
            return self._log(self._template(inp, base, [*limitations, NO_LLM_NOTE_AR]))

        messages = build_messages(
            alert=alert_data, current_snapshot=current_data, previous_snapshot=previous_data
        )
        draft, outcome = await generate_validated(
            self._llm,
            messages,
            AlertExplanationDraft,
            lambda d: self.validate_draft(d, inp, allowed),
            label="alert_explanation",
        )
        if draft is None:
            return self._log(self._template(inp, base, limitations))
        return self._log(
            AlertExplanationResponse(
                **base,
                summary_ar=draft.summary_ar,
                explanation_ar=draft.explanation_ar,
                key_factors=draft.key_factors,
                risks_ar=draft.risks_ar,
                limitations_ar=dedupe([*limitations, *draft.limitations_ar]),
                generation=outcome,
            )
        )

    # ── Validation ────────────────────────────────────────────────────

    @staticmethod
    def validate_draft(
        draft: AlertExplanationDraft, inp: AlertExplanationInput, allowed: set[float]
    ) -> list[str]:
        issues = text_issues(draft.summary_ar, "summary_ar", allowed)
        issues += text_issues(draft.explanation_ar, "explanation_ar", allowed)
        for note in draft.risks_ar:
            issues += text_issues(note, "risks_ar", allowed)
        for note in draft.limitations_ar:
            issues += text_issues(note, "limitations_ar", allowed)
        for factor in draft.key_factors:
            issues += text_issues(factor.factor, "key_factors.factor", allowed)
            issues += text_issues(factor.interpretation_ar, "key_factors.interpretation_ar", allowed)
            if isinstance(factor.value, str):
                issues += text_issues(factor.value, "key_factors.value", allowed)
            elif factor.value is not None and not is_grounded(number_text(factor.value), allowed):
                issues.append(f"key_factors value {factor.value} is not in the supplied data")

        body = normalize_digits(f"{draft.summary_ar} {draft.explanation_ar}")
        day = (inp.data_date or inp.observed_at.date()).isoformat()
        if day not in body:
            issues.append(f"State the data date {day} in summary_ar or explanation_ar")
        if inp.observed_value is not None and not any(
            is_grounded(n, {abs(inp.observed_value)}) for n in extract_numbers(draft.explanation_ar)
        ):
            issues.append("explanation_ar must state the alert's observed_value")
        return issues

    # ── Deterministic parts ───────────────────────────────────────────

    @staticmethod
    def _base_limitations(
        inp: AlertExplanationInput,
        current: TechnicalSnapshot | None,
        previous: TechnicalSnapshot | None,
    ) -> list[str]:
        notes = [NEWS_NOT_SEARCHED_AR]
        if inp.data_date is None:
            notes.append("تاريخ البيانات غير مسجل في التنبيه؛ يُستخدم تاريخ إنشاء التنبيه بدلًا منه.")
        elif current is None:
            notes.append(f"لا توجد لقطة فنية مخزنة للسهم {inp.ticker} بتاريخ التنبيه.")
        if inp.data_date is not None and previous is None:
            notes.append("لا توجد لقطة فنية سابقة للمقارنة.")
        return notes

    @staticmethod
    def _sources(
        inp: AlertExplanationInput,
        current: TechnicalSnapshot | None,
        previous: TechnicalSnapshot | None,
    ) -> list[SourceRef]:
        sources = [
            SourceRef(
                source_type="monitoring_alert",
                source_id=str(inp.alert_id),
                as_of=inp.data_date or inp.observed_at.date(),
            )
        ]
        for snapshot in (current, previous):
            if snapshot is not None:
                sources.append(
                    SourceRef(source_type="technical_snapshot", source_id=str(snapshot.id), as_of=snapshot.date)
                )
        return sources

    @staticmethod
    def _template(
        inp: AlertExplanationInput, base: dict[str, Any], limitations: list[str]
    ) -> AlertExplanationResponse:
        t, ev = inp.ticker, inp.evidence
        day = (inp.data_date or inp.observed_at.date()).isoformat()
        obs, thr = _fmt(inp.observed_value), _fmt(inp.threshold_value)
        above = inp.direction != "below"

        if inp.alert_type == "rsi_threshold":
            side = "أعلى من" if above else "أقل من"
            summary = f"مؤشر القوة النسبية لسهم {t} {side} الحد المحدد في القاعدة."
            explanation = (
                f"أُطلق التنبيه لأن مؤشر القوة النسبية لسهم {t} بلغ {obs} بتاريخ {day}، "
                f"وهو {side} الحد المحدد في القاعدة ({thr})."
            )
        elif inp.alert_type == "price_ma_cross":
            period = next((k.removeprefix("sma_") for k in ("sma_20", "sma_50") if k in ev), None)
            ma = f"المتوسط المتحرك لـ{period} جلسة" if period else "المتوسط المتحرك"
            side = "صعودًا فوق" if above else "هبوطًا تحت"
            summary = f"عبر سعر سهم {t} {side} {ma}."
            explanation = (
                f"أُطلق التنبيه لأن سعر الإغلاق لسهم {t} ({obs}) عبر {side} {ma} ({thr}) بتاريخ {day}."
            )
        elif inp.alert_type == "volatility_threshold":
            summary = f"تجاوز تقلب سهم {t} الحد المحدد في القاعدة."
            explanation = (
                f"أُطلق التنبيه لأن نسبة متوسط المدى الحقيقي إلى سعر الإغلاق لسهم {t} بلغت {obs}% "
                f"بتاريخ {day}، متجاوزةً الحد المحدد في القاعدة ({thr}%)."
            )
        else:  # score_change
            previous, delta = ev.get("previous_score"), ev.get("delta")
            change = f" (فارق {delta:+.2f})" if isinstance(delta, (int, float)) else ""
            summary = f"تغيرت الدرجة الفنية المركبة لسهم {t} بمقدار يتجاوز الحد المحدد."
            explanation = (
                f"أُطلق التنبيه لأن الدرجة الفنية المركبة لسهم {t} تغيرت من {_fmt(previous)} "
                f"إلى {obs}{change} بتاريخ {day}، وهو تغير يتجاوز الحد المحدد في القاعدة ({thr})."
            )

        factors = [
            AlertKeyFactor(factor="observed_value", value=inp.observed_value, interpretation_ar="القيمة المرصودة عند إطلاق التنبيه."),
            AlertKeyFactor(factor="threshold_value", value=inp.threshold_value, interpretation_ar="الحد المحدد في قاعدة المراقبة."),
        ]
        return AlertExplanationResponse(
            **base,
            summary_ar=summary,
            explanation_ar=explanation,
            key_factors=factors,
            risks_ar=[TEMPLATE_RISK_AR],
            limitations_ar=dedupe(limitations),
            generation="fallback",
        )

    def _log(self, response: AlertExplanationResponse) -> AlertExplanationResponse:
        logger.info(
            "alert explained alert_id=%s type=%s generation=%s prompt=%s model=%s",
            response.alert_id,
            response.alert_type,
            response.generation,
            PROMPT_VERSION,
            getattr(self._llm, "model_name", None),
        )
        return response
