"""Explanation Agent settings (env prefix ``EXPLANATION_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExplanationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EXPLANATION_",
        env_file=".env",
        extra="ignore",
    )

    # Groq model for Arabic generation. Falls back to NEWS_ANALYSIS_MODEL when
    # unset; with no model or key configured, explanations use safe templates.
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0)

    # A snapshot older than this many calendar days is reported as stale. EGX
    # closes Friday and Saturday, so a small buffer covers normal weekends.
    max_snapshot_age_days: int = Field(default=4, ge=0)

    rate_limit_per_minute: int = Field(default=20, ge=1)


@lru_cache
def get_explanation_settings() -> ExplanationSettings:
    return ExplanationSettings()
