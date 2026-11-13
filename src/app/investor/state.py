"""LangGraph state contract for the Investor Agent interview workflow."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class InvestorAgentState(TypedDict, total=False):
    """Durable interview thread state persisted by the LangGraph checkpointer.

    Reference: FinMind Unified Spec, Section 5.2
    """

    # Core thread identifiers
    user_id: str
    session_id: str
    messages: Annotated[list[Any], add_messages]

    # In-progress extracted profile slots
    risk_tolerance_raw: str | None
    risk_capacity_raw: str | None
    risk_capacity: str | None
    risk_willingness: str | None
    derived_risk_profile: str | None
    investment_horizon: str | None
    investment_goal: str | None
    investment_experience: str | None
    excluded_sectors: list[str]
    excluded_tickers: list[str]
    preferred_sectors: list[str]

    # Control and validation flags
    current_dimension: str | None
    missing_dimensions: list[str]
    detected_conflicts: list[str]
    safety_cap_applied: bool
    safety_cap_reason_ar: str | None
    zero_loss_high_return_claim: bool
    off_topic_redirect: bool
    is_complete: bool
    is_confirmed: bool
    agent_message_ar: str
    clarification_prompt_ar: str | None
    summary_card_ar: dict[str, Any] | None

