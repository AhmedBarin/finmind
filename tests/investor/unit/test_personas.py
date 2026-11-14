"""Persona-based interview tests (Spec Section 12.1) using the keyword extractor."""

from uuid import uuid4

import pytest

from app.investor.checkpointer import create_memory_checkpointer
from app.investor.graph import build_interview_graph, run_interview_turn
from app.investor.schemas import InterviewMessageResponse


async def _converse(messages: list[str]) -> list[InterviewMessageResponse]:
    graph = build_interview_graph(checkpointer=create_memory_checkpointer())
    user_id, session_id = uuid4(), uuid4()
    return [
        await run_interview_turn(graph, user_id=user_id, session_id=session_id, message=m)
        for m in messages
    ]


@pytest.mark.asyncio
async def test_persona_1_retired_saver_is_conservative_long_preservation() -> None:
    turns = await _converse(
        [
            "هدفي الحفاظ على مدخراتي بعد التقاعد",
            "طويل الأجل",
            "الأموال فائضة ومستقرة لكني متحفظ ولا أتحمل الخسارة",
            "خبرة متوسطة",
        ]
    )
    final = turns[-1]
    assert final.state.is_complete is True
    assert final.summary_card is not None
    params = final.summary_card.extracted_parameters
    assert params.risk_profile.value == "conservative"
    assert params.investment_horizon.value == "long"
    assert params.investment_goal.value == "capital_preservation"
    assert final.state.safety_cap_applied is False


@pytest.mark.asyncio
async def test_persona_2_day_trader_is_aggressive_short_speculation_tech_open() -> None:
    turns = await _converse(
        [
            "هدفي المضاربة السريعة وأفضل قطاع التكنولوجيا",
            "قصير الأجل أيام إلى أسابيع",
            "عندي فائض كبير لا أحتاجها وأقبل المخاطرة العالية",
            "محترف وخبرة متقدمة",
        ]
    )
    params = turns[-1].summary_card.extracted_parameters
    assert params.risk_profile.value == "aggressive"
    assert params.investment_horizon.value == "short"
    assert params.investment_goal.value == "speculation"
    assert params.investment_experience.value == "advanced"
    assert params.preferred_sectors == ["Technology"]


@pytest.mark.asyncio
async def test_persona_3_moderate_employee_is_moderate_medium_growth() -> None:
    turns = await _converse(
        [
            "هدفي تنمية رأس المال وأركز على أسهم EGX30",
            "متوسط الأجل من 1 إلى 6 أشهر",
            "الأموال فائضة عن حاجتي وأتحمل تقلبات معقولة",
            "خبرتي متوسطة",
        ]
    )
    params = turns[-1].summary_card.extracted_parameters
    assert params.risk_profile.value == "moderate"
    assert params.investment_horizon.value == "medium"
    assert params.investment_goal.value == "growth"
    # EGX30 is an index, not a ticker to exclude.
    assert params.excluded_tickers == []


@pytest.mark.asyncio
async def test_persona_4_conflicted_novice_triggers_resolution_then_moderate_cap() -> None:
    turns = await _converse(
        [
            "أريد تحقيق أرباح 30% خلال أسبوعين بدون أي مخاطرة",
            "أختار النمو",
            "الأموال مرتبطة بالتزامات قريبة لكن أقبل المخاطرة",
            "مبتدئ",
        ]
    )
    first = turns[0]
    assert "zero_risk_high_return_contradiction" in first.state.detected_conflicts
    assert first.summary_card is None
    assert "العائد" in first.agent_message_ar

    final = turns[-1]
    assert final.state.is_complete is True
    assert final.state.safety_cap_applied is True
    params = final.summary_card.extracted_parameters
    assert params.risk_profile.value == "moderate"
    assert params.investment_experience.value == "beginner"
