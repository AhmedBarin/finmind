"""Investor Agent orchestration: interview turns, HITL confirmation, review status.

Route handlers stay thin; this module owns session ownership checks, the HITL
gate, and the link between the interview graph and persistence/memory.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.investor import repository
from app.investor.graph import (
    get_session_values,
    mark_session_confirmed,
    run_interview_turn,
    state_to_response,
)
from app.investor.memory import (
    PreferenceMemory,
    ProfileReviewStatus,
    detect_life_event,
    evaluate_review_triggers,
    record_life_event,
    redact_state_for_logging,
)
from app.investor.schemas import (
    RISK_PROFILE_RANK,
    ConfirmedProfileResponse,
    HITLSummaryCard,
    InterviewMessageResponse,
    InvestorProfileConfirmRequest,
    InvestorProfilePayload,
    RiskProfile,
    SessionConfirmRequest,
)

logger = logging.getLogger(__name__)

RISK_OVERRIDE_DISCLAIMER_AR = (
    "تنبيه هام: اخترت مستوى مخاطرة أعلى من المستوى المحسوب لك بناءً على قدرتك المالية "
    "وإجاباتك. قد يعرضك ذلك لتقلبات وخسائر أكبر في رأس المال. "
    "يرجى تأكيد قبولك لهذا التنبيه لتفعيل الملف."
)

CONFIRMED_MESSAGE_AR = (
    "تم تأكيد وتفعيل ملفك الاستثماري بنجاح. "
    "سيستخدم محرك التوصيات هذا الملف عند تقييم الأسهم المناسبة لك."
)


class InvestorServiceError(Exception):
    """Base class for errors mapped to HTTP responses by the router."""

    status_code = 400

    def __init__(self, detail: Any) -> None:
        super().__init__(str(detail))
        self.detail = detail


class SessionNotFoundError(InvestorServiceError):
    status_code = 404


class SessionAlreadyConfirmedError(InvestorServiceError):
    status_code = 409


class SessionNotReadyError(InvestorServiceError):
    status_code = 409


class RiskDisclaimerRequiredError(InvestorServiceError):
    status_code = 422


class ProfileNotFoundError(InvestorServiceError):
    status_code = 404


def _assert_owner(values: dict[str, Any], user_id: UUID) -> None:
    """Hide sessions owned by other users behind a 404 (no existence leak)."""
    owner = values.get("user_id")
    if owner is not None and owner != str(user_id):
        raise SessionNotFoundError("Interview session not found")


async def handle_interview_message(
    graph: Any,
    session: AsyncSession,
    memory: PreferenceMemory,
    *,
    user_id: UUID,
    session_id: UUID,
    message: str,
) -> InterviewMessageResponse:
    """Run one interview turn after ownership and HITL-gate checks."""
    values = await get_session_values(graph, session_id)
    _assert_owner(values, user_id)
    if values.get("is_confirmed"):
        raise SessionAlreadyConfirmedError(
            "This interview is already confirmed. Start a new session to re-profile."
        )

    response = await run_interview_turn(
        graph, user_id=user_id, session_id=session_id, message=message
    )

    # Life events only matter for an existing active profile (re-profiling trigger).
    event = detect_life_event(message)
    if event is not None and await repository.get_active_profile(session, user_id):
        await record_life_event(memory, session, user_id, event)

    logger.info(
        "Investor interview turn",
        extra={
            "session_id": str(session_id),
            "step": response.state.current_step,
            "is_complete": response.state.is_complete,
        },
    )
    return response


async def get_interview_session(
    graph: Any,
    *,
    user_id: UUID,
    session_id: UUID,
) -> InterviewMessageResponse:
    """Return the latest checkpointed turn so an abandoned interview can resume."""
    values = await get_session_values(graph, session_id)
    if not values:
        raise SessionNotFoundError("Interview session not found")
    _assert_owner(values, user_id)
    return state_to_response(session_id, values)


def build_confirmation(
    card: HITLSummaryCard,
    request: SessionConfirmRequest,
) -> InvestorProfileConfirmRequest:
    """Apply validated user edits to the summary card and enforce the risk disclaimer."""
    params = card.extracted_parameters
    overrides = (
        request.user_overrides.model_dump(exclude_none=True)
        if request.user_overrides is not None
        else {}
    )
    merged = {
        "risk_profile": params.risk_profile,
        "investment_horizon": params.investment_horizon,
        "investment_goal": params.investment_goal,
        "investment_experience": params.investment_experience,
        "excluded_sectors": params.excluded_sectors,
        "excluded_tickers": params.excluded_tickers,
        "preferred_sectors": params.preferred_sectors,
        **overrides,
        "reason": request.reason,
    }
    confirmation = InvestorProfileConfirmRequest.model_validate(merged)

    derived = RiskProfile(params.risk_profile)
    if (
        RISK_PROFILE_RANK[confirmation.risk_profile] > RISK_PROFILE_RANK[derived]
        and not request.accept_risk_disclaimer
    ):
        raise RiskDisclaimerRequiredError(
            {
                "code": "risk_disclaimer_required",
                "derived_risk_profile": derived.value,
                "requested_risk_profile": confirmation.risk_profile.value,
                "disclaimer_ar": RISK_OVERRIDE_DISCLAIMER_AR,
            }
        )
    return confirmation


async def confirm_session_profile(
    graph: Any,
    session: AsyncSession,
    *,
    user_id: UUID,
    request: SessionConfirmRequest,
) -> ConfirmedProfileResponse:
    """HITL gate: persist and activate a profile only on explicit confirmation."""
    values = await get_session_values(graph, request.session_id)
    if not values:
        raise SessionNotFoundError("Interview session not found")
    _assert_owner(values, user_id)
    if values.get("is_confirmed"):
        raise SessionAlreadyConfirmedError("This interview is already confirmed")
    summary_raw = values.get("summary_card_ar")
    if not values.get("is_complete") or summary_raw is None:
        raise SessionNotReadyError(
            {
                "code": "interview_incomplete",
                "missing_dimensions": list(values.get("missing_dimensions") or []),
            }
        )

    confirmation = build_confirmation(
        HITLSummaryCard.model_validate(summary_raw), request
    )
    profile = await repository.confirm_and_activate_profile(
        session, user_id, confirmation
    )
    payload = InvestorProfilePayload.model_validate(profile)
    # Commit before closing the graph gate so a DB failure leaves the session open.
    await session.commit()

    await mark_session_confirmed(
        graph,
        session_id=request.session_id,
        profile_id=profile.id,
        message_ar=CONFIRMED_MESSAGE_AR,
    )
    logger.info(
        "Investor profile confirmed",
        extra={
            "profile_version": payload.profile_version,
            "state": redact_state_for_logging(
                {"risk_profile": payload.risk_profile.value}
            ),
        },
    )
    return ConfirmedProfileResponse(
        profile_id=profile.id,
        profile=payload,
        agent_message_ar=CONFIRMED_MESSAGE_AR,
    )


async def get_review_status(
    session: AsyncSession,
    memory: PreferenceMemory,
    *,
    user_id: UUID,
) -> ProfileReviewStatus:
    """Evaluate re-profiling triggers without modifying the active profile."""
    profile = await repository.get_active_profile(session, user_id)
    if profile is None:
        return ProfileReviewStatus(has_active_profile=False)
    triggers = evaluate_review_triggers(profile, await memory.recall(session, user_id))
    return ProfileReviewStatus(
        has_active_profile=True,
        profile_version=profile.profile_version,
        needs_review=bool(triggers),
        triggers=triggers,
    )
