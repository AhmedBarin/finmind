"""Arabic HITL summary card builder for Investor Agent review."""

from __future__ import annotations

from app.investor.schemas import (
    ExtractedProfileParameters,
    HITLSummaryCard,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    ProfileSummaryCardAr,
    RiskProfile,
    compute_gating_parameters,
)

_RISK_DISPLAY_AR: dict[RiskProfile, str] = {
    RiskProfile.CONSERVATIVE: "متحفظ (Conservative)",
    RiskProfile.MODERATE: "معتدل (Moderate)",
    RiskProfile.AGGRESSIVE: "مرتفع المخاطرة (Aggressive)",
}

_HORIZON_DISPLAY_AR: dict[InvestmentHorizon, str] = {
    InvestmentHorizon.SHORT: "قصير الأجل (أيام إلى أسابيع)",
    InvestmentHorizon.MEDIUM: "متوسط الأجل (1 إلى 6 أشهر)",
    InvestmentHorizon.LONG: "طويل الأجل (أكثر من 6 أشهر)",
}

_GOAL_DISPLAY_AR: dict[InvestmentGoal, str] = {
    InvestmentGoal.CAPITAL_PRESERVATION: "الحفاظ على رأس المال والتحوط",
    InvestmentGoal.GROWTH: "تنمية رأس المال",
    InvestmentGoal.INCOME: "تحقيق عوائد دورية (توزيعات أرباح)",
    InvestmentGoal.SPECULATION: "المضاربة والاستفادة من الزخم السعري",
}

_EXPERIENCE_DISPLAY_AR: dict[InvestmentExperience, str] = {
    InvestmentExperience.BEGINNER: "مبتدئ (أقل من سنة في البورصة المصرية)",
    InvestmentExperience.INTERMEDIATE: "متوسط (1 إلى 3 سنوات في البورصة المصرية)",
    InvestmentExperience.ADVANCED: "متقدم (أكثر من 3 سنوات وخبرة فنية)",
}


def build_hitl_summary_card(
    *,
    risk_profile: RiskProfile,
    investment_horizon: InvestmentHorizon,
    investment_goal: InvestmentGoal,
    investment_experience: InvestmentExperience,
    excluded_sectors: list[str] | None = None,
    excluded_tickers: list[str] | None = None,
    preferred_sectors: list[str] | None = None,
) -> HITLSummaryCard:
    """Construct the structured Arabic review card for explicit HITL confirmation."""
    liquidity_floor, max_atr_cap = compute_gating_parameters(risk_profile)
    extracted = ExtractedProfileParameters(
        risk_profile=risk_profile,
        investment_horizon=investment_horizon,
        investment_goal=investment_goal,
        investment_experience=investment_experience,
        excluded_sectors=excluded_sectors or [],
        excluded_tickers=excluded_tickers or [],
        preferred_sectors=preferred_sectors or [],
        liquidity_floor_pct=liquidity_floor,
        max_atr_pctl_cap=max_atr_cap,
    )

    constraints_summary: list[str] = []
    if extracted.excluded_sectors:
        constraints_summary.append(
            f"استبعاد القطاعات التالية: {', '.join(extracted.excluded_sectors)}"
        )
    if extracted.excluded_tickers:
        constraints_summary.append(
            f"استبعاد الأسهم التالية: {', '.join(extracted.excluded_tickers)}"
        )
    if extracted.preferred_sectors:
        constraints_summary.append(
            f"تفضيل القطاعات التالية: {', '.join(extracted.preferred_sectors)}"
        )
    if not constraints_summary:
        constraints_summary.append("لا توجد قيود أو استثناءات مضافة على القطاعات أو الأسهم.")

    impact_text = (
        f"سيتم ترشيح الأسهم ضمن أعلى {int(liquidity_floor)}% سيولة في السوق، "
        f"مع استبعاد الأسهم التي يتجاوز تذبذبها (ATR) نسبة {int(max_atr_cap)}%."
    )

    return HITLSummaryCard(
        profile_summary_ar=ProfileSummaryCardAr(
            title="ملخص الملف الاستثماري الخاص بك",
            risk_level_display=_RISK_DISPLAY_AR[risk_profile],
            horizon_display=_HORIZON_DISPLAY_AR[investment_horizon],
            goal_display=_GOAL_DISPLAY_AR[investment_goal],
            experience_display=_EXPERIENCE_DISPLAY_AR[investment_experience],
            constraints_summary=constraints_summary,
            recommendation_engine_impact=impact_text,
        ),
        extracted_parameters=extracted,
        requires_user_confirmation=True,
    )

