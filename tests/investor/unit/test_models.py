"""Unit tests for Investor Agent SQLAlchemy ORM models."""

from app.investor.models import InvestorProfile, LearnedPreference, ProfileAuditLog


def test_investor_profile_table_structure() -> None:
    assert InvestorProfile.__tablename__ == "investor_profiles"
    columns = set(InvestorProfile.__table__.columns.keys())
    expected = {
        "id",
        "user_id",
        "risk_profile",
        "investment_horizon",
        "investment_goal",
        "investment_experience",
        "liquidity_floor_pct",
        "max_atr_pctl_cap",
        "excluded_sectors",
        "excluded_tickers",
        "preferred_sectors",
        "is_active",
        "profile_version",
        "confirmed_at",
        "last_reviewed_at",
        "created_at",
        "updated_at",
    }
    assert expected == columns

    # Ensure no premature foreign key to an unbuilt shared users table.
    assert not InvestorProfile.__table__.c.user_id.foreign_keys

    indexes = {idx.name: idx for idx in InvestorProfile.__table__.indexes}
    assert "ix_investor_profiles_user_id" in indexes
    assert "uq_user_active_profile" in indexes
    active_idx = indexes["uq_user_active_profile"]
    assert active_idx.unique is True
    assert "is_active IS TRUE" in str(active_idx.dialect_options["postgresql"]["where"])


def test_profile_audit_log_table_structure() -> None:
    assert ProfileAuditLog.__tablename__ == "profile_audit_logs"
    columns = set(ProfileAuditLog.__table__.columns.keys())
    expected = {
        "id",
        "profile_id",
        "user_id",
        "change_type",
        "previous_state",
        "new_state",
        "reason",
        "changed_by",
        "created_at",
    }
    assert expected == columns

    fk_targets = {
        fk.target_fullname
        for fk in ProfileAuditLog.__table__.c.profile_id.foreign_keys
    }
    assert fk_targets == {"investor_profiles.id"}


def test_learned_preference_table_structure() -> None:
    assert LearnedPreference.__tablename__ == "learned_preferences"
    columns = set(LearnedPreference.__table__.columns.keys())
    expected = {
        "id",
        "user_id",
        "preference_key",
        "preference_value",
        "confidence_score",
        "source_event",
        "user_validated",
        "created_at",
        "updated_at",
    }
    assert expected == columns

    constraints = {c.name for c in LearnedPreference.__table__.constraints}
    assert "uq_user_preference_key" in constraints
    assert "ck_learned_preferences_confidence_range" in constraints

