"""Database repository for Investor Agent profiles, audit logs, and learned preferences.

Functions accept an ``AsyncSession`` and leave transaction boundaries to the
caller so service and API handlers can compose operations atomically.
All queries strictly scope access by ``user_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.investor.models import InvestorProfile, LearnedPreference, ProfileAuditLog
from app.investor.schemas import (
    AuditChangedBy,
    ConstraintsUpdateRequest,
    InvestorProfileConfirmRequest,
    InvestorProfilePayload,
    LearnedPreferenceCreate,
    ProfileAuditChangeType,
    compute_gating_parameters,
)


def _profile_snapshot_dict(profile: InvestorProfile) -> dict[str, Any]:
    """Serialize an ORM profile into a JSON-safe audit state snapshot."""
    return {
        "profile_id": str(profile.id),
        "user_id": str(profile.user_id),
        "risk_profile": profile.risk_profile,
        "investment_horizon": profile.investment_horizon,
        "investment_goal": profile.investment_goal,
        "investment_experience": profile.investment_experience,
        "liquidity_floor_pct": float(profile.liquidity_floor_pct),
        "max_atr_pctl_cap": float(profile.max_atr_pctl_cap),
        "excluded_sectors": list(profile.excluded_sectors),
        "excluded_tickers": list(profile.excluded_tickers),
        "preferred_sectors": list(profile.preferred_sectors),
        "is_active": profile.is_active,
        "profile_version": profile.profile_version,
        "confirmed_at": profile.confirmed_at.isoformat()
        if profile.confirmed_at
        else None,
    }


async def get_active_profile(
    session: AsyncSession,
    user_id: UUID,
) -> InvestorProfile | None:
    """Return the user's currently active confirmed profile, or ``None``."""
    stmt = select(InvestorProfile).where(
        InvestorProfile.user_id == user_id,
        InvestorProfile.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_profile_payload(
    session: AsyncSession,
    user_id: UUID,
) -> InvestorProfilePayload | None:
    """Return the canonical Recommendation Engine payload for an active profile."""
    profile = await get_active_profile(session, user_id)
    if profile is None:
        return None
    return InvestorProfilePayload.model_validate(profile)


async def get_profile_history(
    session: AsyncSession,
    user_id: UUID,
) -> list[InvestorProfile]:
    """Return all confirmed profile versions for ``user_id`` newest first."""
    stmt = (
        select(InvestorProfile)
        .where(InvestorProfile.user_id == user_id)
        .order_by(InvestorProfile.profile_version.desc(), InvestorProfile.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def confirm_and_activate_profile(
    session: AsyncSession,
    user_id: UUID,
    confirmation: InvestorProfileConfirmRequest,
    *,
    change_type: ProfileAuditChangeType | None = None,
    changed_by: AuditChangedBy = AuditChangedBy.USER,
    reason: str | None = None,
    confirmed_at: datetime | None = None,
) -> InvestorProfile:
    """Persist a HITL-confirmed profile, deactivate prior versions, and audit."""
    now = confirmed_at or datetime.now(UTC)
    existing_active = await get_active_profile(session, user_id)
    max_version_result = await session.execute(
        select(func.coalesce(func.max(InvestorProfile.profile_version), 0)).where(
            InvestorProfile.user_id == user_id
        )
    )
    next_version = int(max_version_result.scalar_one()) + 1

    previous_state: dict[str, Any] | None = None
    if existing_active is not None:
        previous_state = _profile_snapshot_dict(existing_active)
        existing_active.is_active = False
        # Flush deactivation before inserting new active row to satisfy uq_user_active_profile.
        await session.flush()

    effective_change_type = change_type or (
        ProfileAuditChangeType.RE_PROFILING
        if existing_active is not None
        else ProfileAuditChangeType.INITIAL_CREATION
    )

    liquidity_floor, max_atr_cap = compute_gating_parameters(confirmation.risk_profile)
    profile = InvestorProfile(
        user_id=user_id,
        risk_profile=confirmation.risk_profile.value,
        investment_horizon=confirmation.investment_horizon.value,
        investment_goal=confirmation.investment_goal.value,
        investment_experience=confirmation.investment_experience.value,
        liquidity_floor_pct=Decimal(f"{liquidity_floor:.2f}"),
        max_atr_pctl_cap=Decimal(f"{max_atr_cap:.2f}"),
        excluded_sectors=list(confirmation.excluded_sectors),
        excluded_tickers=list(confirmation.excluded_tickers),
        preferred_sectors=list(confirmation.preferred_sectors),
        is_active=True,
        profile_version=next_version,
        confirmed_at=now,
        last_reviewed_at=now,
    )
    session.add(profile)
    await session.flush()

    audit_entry = ProfileAuditLog(
        profile_id=profile.id,
        user_id=user_id,
        change_type=effective_change_type.value,
        previous_state=previous_state,
        new_state=_profile_snapshot_dict(profile),
        reason=reason if reason is not None else confirmation.reason,
        changed_by=changed_by.value,
    )
    session.add(audit_entry)
    await session.flush()
    await session.refresh(profile)
    return profile


async def update_profile_constraints(
    session: AsyncSession,
    user_id: UUID,
    update: ConstraintsUpdateRequest,
    *,
    changed_by: AuditChangedBy = AuditChangedBy.USER,
) -> InvestorProfile | None:
    """Update constraints on the active profile, bump version, and append audit log."""
    profile = await get_active_profile(session, user_id)
    if profile is None:
        return None

    previous_state = _profile_snapshot_dict(profile)
    if update.excluded_sectors is not None:
        profile.excluded_sectors = list(update.excluded_sectors)
    if update.excluded_tickers is not None:
        profile.excluded_tickers = list(update.excluded_tickers)
    if update.preferred_sectors is not None:
        profile.preferred_sectors = list(update.preferred_sectors)

    profile.profile_version += 1
    profile.last_reviewed_at = datetime.now(UTC)
    await session.flush()

    audit_entry = ProfileAuditLog(
        profile_id=profile.id,
        user_id=user_id,
        change_type=ProfileAuditChangeType.USER_EDIT.value,
        previous_state=previous_state,
        new_state=_profile_snapshot_dict(profile),
        reason=update.reason,
        changed_by=changed_by.value,
    )
    session.add(audit_entry)
    await session.flush()
    await session.refresh(profile)
    return profile


async def list_audit_logs(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int = 50,
) -> list[ProfileAuditLog]:
    """Return immutable profile audit logs for ``user_id`` newest first."""
    stmt = (
        select(ProfileAuditLog)
        .where(ProfileAuditLog.user_id == user_id)
        .order_by(ProfileAuditLog.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_learned_preference(
    session: AsyncSession,
    user_id: UUID,
    preference: LearnedPreferenceCreate,
) -> LearnedPreference:
    """Insert or update a learned preference without modifying active profile gates."""
    values = {
        "user_id": user_id,
        "preference_key": preference.preference_key,
        "preference_value": dict(preference.preference_value),
        "confidence_score": Decimal(f"{preference.confidence_score:.2f}"),
        "source_event": preference.source_event,
        "user_validated": preference.user_validated,
    }
    stmt = pg_insert(LearnedPreference).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_preference_key",
        set_={
            "preference_value": stmt.excluded.preference_value,
            "confidence_score": stmt.excluded.confidence_score,
            "source_event": stmt.excluded.source_event,
            "user_validated": stmt.excluded.user_validated,
            "updated_at": func.now(),
        },
    ).returning(LearnedPreference)
    result = await session.execute(stmt)
    return result.scalar_one()


async def list_learned_preferences(
    session: AsyncSession,
    user_id: UUID,
    *,
    validated_only: bool = False,
) -> list[LearnedPreference]:
    """Return learned preferences scoped to ``user_id``."""
    stmt = select(LearnedPreference).where(LearnedPreference.user_id == user_id)
    if validated_only:
        stmt = stmt.where(LearnedPreference.user_validated.is_(True))
    stmt = stmt.order_by(LearnedPreference.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())

