"""Unit tests for the stateful LangGraph investor interview workflow."""

from uuid import uuid4

import pytest

from app.investor.checkpointer import create_memory_checkpointer
from app.investor.graph import build_interview_graph, run_interview_turn
from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskProfile,
)


@pytest.mark.asyncio
async def test_multi_turn_interview_persists_state_and_emits_hitl_card() -> None:
    graph = build_interview_graph(checkpointer=create_memory_checkpointer())
    user_id = uuid4()
    session_id = uuid4()

    # Turn 1: Goal -> asks for horizon
    turn1 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="هدفي تنمية رأس المال واستبعاد قطاع التبغ",
    )
    assert turn1.state.is_complete is False
    assert turn1.state.current_step == "investment_horizon"
    assert turn1.summary_card is None

    # Turn 2: Horizon -> asks for risk capacity & tolerance
    turn2 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="متوسط الأجل من 1 إلى 6 أشهر",
    )
    assert turn2.state.is_complete is False
    assert turn2.state.current_step == "risk_profile"
    assert "investment_horizon" not in turn2.state.missing_dimensions

    # Turn 3: Risk -> asks for experience
    turn3 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="الأموال فائضة عن حاجتي وأتحمل تقلبات معقولة بشكل معتدل",
    )
    assert turn3.state.is_complete is False
    assert turn3.state.current_step == "investment_experience"

    # Turn 4: Experience -> produces Arabic HITL summary card without auto-confirming
    turn4 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="خبرة متوسطة في البورصة المصرية",
    )
    assert turn4.state.is_complete is True
    assert turn4.state.current_step == "hitl_confirmation"
    assert turn4.summary_card is not None
    assert turn4.summary_card.requires_user_confirmation is True
    params = turn4.summary_card.extracted_parameters
    assert params.risk_profile is RiskProfile.MODERATE
    assert params.investment_horizon is InvestmentHorizon.MEDIUM
    assert params.investment_goal is InvestmentGoal.GROWTH
    assert params.investment_experience is InvestmentExperience.INTERMEDIATE
    assert params.excluded_sectors == ["Tobacco"]
    assert params.liquidity_floor_pct == 70.0
    assert params.max_atr_pctl_cap == 75.0


@pytest.mark.asyncio
async def test_contradiction_triggers_clarification_before_safety_capped_completion() -> None:
    graph = build_interview_graph(checkpointer=create_memory_checkpointer())
    user_id = uuid4()
    session_id = uuid4()

    # Persona 4: Contradictory zero-risk + high-return input
    turn1 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="أريد ربح سريع 30% خلال أسبوعين بدون أي مخاطرة",
    )
    assert turn1.state.is_complete is False
    assert "zero_risk_high_return_contradiction" in turn1.state.detected_conflicts
    assert turn1.summary_card is None

    # Clarification + low capacity + aggressive willingness -> safety cap to Moderate
    turn2 = await run_interview_turn(
        graph,
        user_id=user_id,
        session_id=session_id,
        message="حسناً هدفي تنمية رأس المال طويل الأجل، هذه أموال طوارئ لكن أقبل المخاطرة عالية، خبرتي مبتدئ",
    )
    assert turn2.state.is_complete is True
    assert turn2.state.detected_conflicts == []
    assert turn2.state.safety_cap_applied is True
    assert turn2.summary_card is not None
    assert turn2.summary_card.extracted_parameters.risk_profile is RiskProfile.MODERATE
    assert turn2.summary_card.extracted_parameters.liquidity_floor_pct == 70.0


@pytest.mark.asyncio
async def test_off_topic_stock_query_redirects_without_recommendation() -> None:
    graph = build_interview_graph(checkpointer=create_memory_checkpointer())
    turn = await run_interview_turn(
        graph,
        user_id=uuid4(),
        session_id=uuid4(),
        message="هل أشتري سهم COMI دلوقتي؟",
    )
    assert turn.state.is_complete is False
    assert turn.summary_card is None
    assert "لا يمكنني ترشيح أسهم" in turn.agent_message_ar

