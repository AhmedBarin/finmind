"""LangGraph stateful interview workflow for the Investor Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Protocol
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.investor.assessment import (
    is_off_topic_stock_query,
    validate_coherence,
)
from app.investor.schemas import (
    HITLSummaryCard,
    InterviewMessageResponse,
    InterviewStateView,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskCapacity,
    RiskProfile,
    RiskWillingness,
)
from app.investor.state import InvestorAgentState
from app.investor.summary import build_hitl_summary_card

_DIMENSION_QUESTIONS_AR: dict[str, str] = {
    "investment_goal": (
        "أهلاً بك في FinMind. لبدء إعداد ملفك الاستثماري في البورصة المصرية، "
        "ما هو هدفك الأساسي من الاستثمار؟ (الحفاظ على رأس المال، تحقيق دخل دوري من التوزيعات، "
        "تنمية رأس المال على المدى المتوسط والطويل، أم المضاربة السريعة؟)"
    ),
    "investment_horizon": (
        "ما هي المدة الزمنية التي تنوي ترك أموالك مستثمرة فيها دون الحاجة لسحبها؟ "
        "(قصير الأجل: أيام إلى أسابيع، متوسط الأجل: 1 إلى 6 أشهر، أم طويل الأجل: أكثر من 6 أشهر؟)"
    ),
    "risk_profile": (
        "لتحديد درجة المخاطرة المناسبة بدقة: هل هذه الأموال فائضة عن احتياجاتك الأساسية "
        "أم مرتبطة بالتزامات قريبة أو مدخرات طوارئ؟ وكيف تتعامل إذا تراجعت قيمة محفظتك بنسبة 10% إلى 20% مؤقتاً؟"
    ),
    "investment_experience": (
        "ما مستوى خبرتك الحالية في التداول داخل البورصة المصرية (مثل آليات التسوية T+0/T+2 وحدود التذبذب)؟ "
        "(مبتدئ أقل من سنة، متوسط من 1 إلى 3 سنوات، أم متقدم أكثر من 3 سنوات؟)"
    ),
}

_OFF_TOPIC_MESSAGE_AR = (
    "عذراً، لا يمكنني ترشيح أسهم أو تقديم توصيات شراء وبيع أثناء مرحلة المقابلة. "
    "يجب أولاً إتمام وتأكيد ملفك الاستثماري حتى يتمكن محرك التوصيات من تقييم الأسهم المناسبة لك."
)


@dataclass
class ExtractionPatch:
    """Structured slots extracted from a single user message."""

    investment_goal: InvestmentGoal | None = None
    investment_horizon: InvestmentHorizon | None = None
    risk_capacity: RiskCapacity | None = None
    risk_willingness: RiskWillingness | None = None
    risk_capacity_raw: str | None = None
    risk_tolerance_raw: str | None = None
    investment_experience: InvestmentExperience | None = None
    excluded_sectors: list[str] = field(default_factory=list)
    excluded_tickers: list[str] = field(default_factory=list)
    preferred_sectors: list[str] = field(default_factory=list)
    zero_loss_high_return_claim: bool = False


class InterviewTurnExtractor(Protocol):
    """Abstraction allowing Phase 3 LLM extractors to replace deterministic rules."""

    def extract(self, message: str, state: InvestorAgentState) -> ExtractionPatch:
        ...


class RuleBasedArabicExtractor:
    """Deterministic Arabic/English slot extractor for Phase 2 workflow verification."""

    _GOAL_RULES: tuple[tuple[tuple[str, ...], InvestmentGoal], ...] = (
        (("مضاربة", "مضارب", "سريعة", "speculat"), InvestmentGoal.SPECULATION),
        (("توزيعات", "دخل", "أرباح دورية", "income", "dividend"), InvestmentGoal.INCOME),
        (("حماية", "الحفاظ", "مدخرات", "تحوط", "preservation", "preserve"), InvestmentGoal.CAPITAL_PRESERVATION),
        (("تنمية", "نمو", "growth"), InvestmentGoal.GROWTH),
    )

    _HORIZON_RULES: tuple[tuple[tuple[str, ...], InvestmentHorizon], ...] = (
        (("قصير الأجل", "قصير", "أسبوع", "أسبوعين", "أسابيع", "أيام", "يومي", "short"), InvestmentHorizon.SHORT),
        (("متوسط الأجل", "أشهر", "شهور", "1 إلى 6", "medium"), InvestmentHorizon.MEDIUM),
        (("طويل الأجل", "طويل", "عام", "سنة", "سنوات", "أكثر من 6", "long"), InvestmentHorizon.LONG),
    )

    _CAPACITY_RULES: tuple[tuple[tuple[str, ...], RiskCapacity], ...] = (
        (("طوارئ", "التزامات", "ديون", "قرض", "محتاجها قريب", "مرتبطة", "low capacity"), RiskCapacity.LOW),
        (("فائض كبير", "قدرة عالية", "سيولة مرتفعة", "لا أحتاجها", "high capacity"), RiskCapacity.HIGH),
        (("فائضة", "فائض", "مستقرة", "قدرة متوسطة", "medium capacity"), RiskCapacity.MEDIUM),
    )

    _WILLINGNESS_RULES: tuple[tuple[tuple[str, ...], RiskWillingness], ...] = (
        (("متحفظ", "لا أتحمل", "أرفض الخسارة", "أقل مخاطرة", "conservative"), RiskWillingness.CONSERVATIVE),
        (("أتحمل التذبذب", "مخاطرة عالية", "أقبل المخاطرة", "مخاطرة مرتفعة", "هجومي", "aggressive"), RiskWillingness.AGGRESSIVE),
        (("معتدل", "متوازن", "تقلبات معقولة", "مخاطرة متوسطة", "moderate"), RiskWillingness.MODERATE),
    )

    _EXPERIENCE_RULES: tuple[tuple[tuple[str, ...], InvestmentExperience], ...] = (
        (("خبرة متقدمة", "متقدم", "خبرة طويلة", "أكثر من 3 سنوات", "محترف", "advanced"), InvestmentExperience.ADVANCED),
        (("خبرة متوسطة", "خبرتي متوسطة", "سنة إلى 3", "intermediate"), InvestmentExperience.INTERMEDIATE),
        (("مبتدئ", "جديد", "أول مرة", "أقل من سنة", "beginner"), InvestmentExperience.BEGINNER),
    )

    _NO_RISK_HIGH_RETURN_RE = re.compile(
        r"(بدون\s*(?:أي\s*)?مخاطر(?:ة)?|بلا\s*خسار(?:ة)?|zero\s*risk|no\s*risk)"
    )
    _HIGH_RETURN_RE = re.compile(r"(ربح\s*سريع|أرباح\s*(?:عالية|سريعة)|30%|مضاربة|high\s*return)")

    def extract(self, message: str, state: InvestorAgentState) -> ExtractionPatch:
        text = message.strip()
        lowered = text.lower()
        current_dim = state.get("current_dimension")
        patch = ExtractionPatch()

        for keywords, goal in self._GOAL_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_goal = goal
                break

        for keywords, horizon in self._HORIZON_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_horizon = horizon
                break
        if patch.investment_horizon is None and current_dim == "investment_horizon" and "متوسط" in lowered:
            patch.investment_horizon = InvestmentHorizon.MEDIUM

        for keywords, capacity in self._CAPACITY_RULES:
            if any(kw in lowered for kw in keywords):
                patch.risk_capacity = capacity
                patch.risk_capacity_raw = text
                break

        for keywords, willingness in self._WILLINGNESS_RULES:
            if any(kw in lowered for kw in keywords):
                patch.risk_willingness = willingness
                patch.risk_tolerance_raw = text
                break

        for keywords, experience in self._EXPERIENCE_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_experience = experience
                break
        if patch.investment_experience is None and current_dim == "investment_experience" and "متوسط" in lowered:
            patch.investment_experience = InvestmentExperience.INTERMEDIATE

        if self._NO_RISK_HIGH_RETURN_RE.search(lowered) and self._HIGH_RETURN_RE.search(lowered):
            patch.zero_loss_high_return_claim = True
            patch.risk_willingness = patch.risk_willingness or RiskWillingness.AGGRESSIVE
            patch.risk_tolerance_raw = text

        if "التبغ" in text or "tobacco" in lowered:
            patch.excluded_sectors.append("Tobacco")
        if "العقارات" in text or "real estate" in lowered:
            if "تفضيل" in text or "أفضل" in text or "prefer" in lowered:
                patch.preferred_sectors.append("Real Estate")
            elif "استبعاد" in text or "بعيد" in text or "exclude" in lowered:
                patch.excluded_sectors.append("Real Estate")

        return patch


def _extract_message_text(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", ""))


def _merge_unique(existing: list[str] | None, additions: list[str]) -> list[str]:
    merged = list(existing or [])
    for item in additions:
        if item and item not in merged:
            merged.append(item)
    return merged


def build_interview_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    extractor: InterviewTurnExtractor | None = None,
):
    """Compile the LangGraph investor interview state machine (Spec Section 5.1)."""
    turn_extractor = extractor or RuleBasedArabicExtractor()

    def parse_and_extract(state: InvestorAgentState) -> dict[str, Any]:
        messages = state.get("messages") or []
        latest_text = _extract_message_text(messages[-1]) if messages else ""

        if not latest_text.strip():
            return {
                "off_topic_redirect": False,
                "zero_loss_high_return_claim": False,
            }

        if is_off_topic_stock_query(latest_text):
            return {
                "off_topic_redirect": True,
                "zero_loss_high_return_claim": False,
            }

        patch = turn_extractor.extract(latest_text, state)
        updates: dict[str, Any] = {
            "off_topic_redirect": False,
            "zero_loss_high_return_claim": patch.zero_loss_high_return_claim,
        }

        if patch.investment_goal is not None:
            updates["investment_goal"] = patch.investment_goal.value
        if patch.investment_horizon is not None:
            updates["investment_horizon"] = patch.investment_horizon.value
        if patch.risk_capacity is not None:
            updates["risk_capacity"] = patch.risk_capacity.value
        if patch.risk_willingness is not None:
            updates["risk_willingness"] = patch.risk_willingness.value
        if patch.risk_capacity_raw is not None:
            updates["risk_capacity_raw"] = patch.risk_capacity_raw
        if patch.risk_tolerance_raw is not None:
            updates["risk_tolerance_raw"] = patch.risk_tolerance_raw
        if patch.investment_experience is not None:
            updates["investment_experience"] = patch.investment_experience.value
        if patch.excluded_sectors:
            updates["excluded_sectors"] = _merge_unique(
                state.get("excluded_sectors"), patch.excluded_sectors
            )
        if patch.excluded_tickers:
            updates["excluded_tickers"] = _merge_unique(
                state.get("excluded_tickers"), patch.excluded_tickers
            )
        if patch.preferred_sectors:
            updates["preferred_sectors"] = _merge_unique(
                state.get("preferred_sectors"), patch.preferred_sectors
            )
        return updates

    def validate_coherence_node(state: InvestorAgentState) -> dict[str, Any]:
        result = validate_coherence(
            investment_goal=state.get("investment_goal"),
            investment_horizon=state.get("investment_horizon"),
            risk_capacity=state.get("risk_capacity"),
            risk_willingness=state.get("risk_willingness"),
            derived_risk_profile=state.get("derived_risk_profile"),
            investment_experience=state.get("investment_experience"),
            zero_loss_high_return_claim=bool(state.get("zero_loss_high_return_claim")),
        )
        return {
            "derived_risk_profile": (
                result.derived_risk_profile.value
                if result.derived_risk_profile is not None
                else None
            ),
            "safety_cap_applied": result.safety_cap_applied,
            "safety_cap_reason_ar": result.cap_reason_ar,
            "detected_conflicts": list(result.conflicts),
            "clarification_prompt_ar": result.clarification_prompt_ar,
            "missing_dimensions": list(result.missing_dimensions),
            "is_complete": result.is_complete,
        }

    def route_after_validation(state: InvestorAgentState) -> str:
        if state.get("off_topic_redirect"):
            return "select_next_question"
        if state.get("detected_conflicts"):
            return "select_next_question"
        if not state.get("is_complete"):
            return "select_next_question"
        return "generate_summary_card"

    def select_next_question(state: InvestorAgentState) -> dict[str, Any]:
        missing = state.get("missing_dimensions") or []
        next_dim = missing[0] if missing else state.get("current_dimension") or "investment_goal"

        if state.get("off_topic_redirect"):
            prompt = f"{_OFF_TOPIC_MESSAGE_AR}\n\n{_DIMENSION_QUESTIONS_AR[next_dim]}"
        elif state.get("detected_conflicts") and state.get("clarification_prompt_ar"):
            prompt = str(state["clarification_prompt_ar"])
        else:
            question = _DIMENSION_QUESTIONS_AR[next_dim]
            if state.get("safety_cap_applied") and state.get("safety_cap_reason_ar"):
                prompt = f"{state['safety_cap_reason_ar']}\n\n{question}"
            else:
                prompt = question

        return {
            "current_dimension": next_dim,
            "agent_message_ar": prompt,
            "summary_card_ar": None,
            "is_confirmed": False,
            "messages": [{"role": "assistant", "content": prompt}],
        }

    def generate_summary_card(state: InvestorAgentState) -> dict[str, Any]:
        card = build_hitl_summary_card(
            risk_profile=RiskProfile(str(state["derived_risk_profile"])),
            investment_horizon=InvestmentHorizon(str(state["investment_horizon"])),
            investment_goal=InvestmentGoal(str(state["investment_goal"])),
            investment_experience=InvestmentExperience(
                str(state["investment_experience"])
            ),
            excluded_sectors=list(state.get("excluded_sectors") or []),
            excluded_tickers=list(state.get("excluded_tickers") or []),
            preferred_sectors=list(state.get("preferred_sectors") or []),
        )
        intro = (
            "اكتملت جميع البيانات المطلوبة لإعداد ملفك الاستثماري. "
            "يرجى مراجعة بطاقة الملخص أدناه وتأكيدها أو تعديلها قبل تفعيل الملف."
        )
        if state.get("safety_cap_applied") and state.get("safety_cap_reason_ar"):
            intro = f"{state['safety_cap_reason_ar']}\n\n{intro}"

        return {
            "current_dimension": "hitl_confirmation",
            "is_complete": True,
            "is_confirmed": False,
            "summary_card_ar": card.model_dump(mode="json"),
            "agent_message_ar": intro,
            "messages": [{"role": "assistant", "content": intro}],
        }

    workflow = StateGraph(InvestorAgentState)
    workflow.add_node("parse_and_extract", parse_and_extract)
    workflow.add_node("validate_coherence", validate_coherence_node)
    workflow.add_node("select_next_question", select_next_question)
    workflow.add_node("generate_summary_card", generate_summary_card)

    workflow.add_edge(START, "parse_and_extract")
    workflow.add_edge("parse_and_extract", "validate_coherence")
    workflow.add_conditional_edges(
        "validate_coherence",
        route_after_validation,
        {
            "select_next_question": "select_next_question",
            "generate_summary_card": "generate_summary_card",
        },
    )
    workflow.add_edge("select_next_question", END)
    workflow.add_edge("generate_summary_card", END)

    return workflow.compile(checkpointer=checkpointer)


async def run_interview_turn(
    graph: Any,
    *,
    user_id: UUID,
    session_id: UUID,
    message: str,
) -> InterviewMessageResponse:
    """Execute one interview turn against the compiled graph and format API response."""
    result: InvestorAgentState = await graph.ainvoke(
        {
            "user_id": str(user_id),
            "session_id": str(session_id),
            "messages": [{"role": "user", "content": message}],
        },
        config={"configurable": {"thread_id": str(session_id)}},
    )
    summary_raw = result.get("summary_card_ar")
    summary_card = (
        HITLSummaryCard.model_validate(summary_raw)
        if summary_raw is not None
        else None
    )
    return InterviewMessageResponse(
        session_id=session_id,
        agent_message_ar=str(result.get("agent_message_ar", "")),
        state=InterviewStateView(
            current_step=result.get("current_dimension"),
            is_complete=bool(result.get("is_complete", False)),
            missing_dimensions=list(result.get("missing_dimensions") or []),
            detected_conflicts=list(result.get("detected_conflicts") or []),
            safety_cap_applied=bool(result.get("safety_cap_applied", False)),
        ),
        summary_card=summary_card,
    )
