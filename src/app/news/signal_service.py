"""Deterministic aggregation of eligible article analyses into company signals."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.news.models import NewsIngestionRun, NewsSignal, NewsSource
from app.news.signal_repository import NewsSignalRepository, SignalCandidate
from app.news.signal_schemas import NewsCoverageStatus, NewsSignalAggregationConfig


class NewsSignalService:
    SIGNAL_VERSION = "news-signal-v1"

    def __init__(self, *, repository: NewsSignalRepository | None = None, config: NewsSignalAggregationConfig | None = None) -> None:
        self.repository = repository or NewsSignalRepository()
        self.config = config or NewsSignalAggregationConfig()

    async def aggregate_company_signal(self, session: AsyncSession, *, company_id: UUID, as_of: datetime | None = None) -> NewsSignal:
        as_of = self._as_utc(as_of or datetime.now(timezone.utc))
        window_start = as_of - self.config.lookback
        candidates = await self.repository.list_company_candidates(session, company_id=company_id, window_start=window_start, window_end=as_of)
        sources = await self.repository.list_enabled_sources(session)
        runs = await self.repository.list_completed_ingestion_runs(session)

        latest, selection_codes = self._latest_per_article(candidates)
        eligible, exclusion_codes = self._eligible_candidates(latest)
        coverage, coverage_codes, freshness = self._coverage(sources, runs, bool(eligible), as_of)
        direction, direction_codes = self._direction(eligible)
        reason_codes = self._unique([*selection_codes, *exclusion_codes, *coverage_codes, *direction_codes])
        input_hash = self._input_hash(company_id, as_of, latest, reason_codes)

        return await self.repository.save_signal(session, values={
            "company_id": company_id,
            "as_of": as_of,
            "window_start": window_start,
            "window_end": as_of,
            "signal_version": self.SIGNAL_VERSION,
            "aggregation_config_version": self.config.version,
            "input_hash": input_hash,
            "direction": direction,
            "article_count": len(latest),
            "eligible_article_count": len(eligible),
            "coverage_status": coverage.value,
            "freshness_seconds": freshness,
            "top_event_types": dict(sorted(Counter(item.analysis.event_type for item in eligible).items())),
            "contributing_article_ids": [str(item.article.id) for item in eligible],
            "contributing_analysis_ids": [str(item.analysis.id) for item in eligible],
            "reason_codes": reason_codes,
            "limitations": self._limitations(coverage, reason_codes),
        })

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _latest_per_article(candidates: list[SignalCandidate]) -> tuple[list[SignalCandidate], list[str]]:
        latest, seen = [], set()
        for item in candidates:
            if item.article.id not in seen:
                latest.append(item)
                seen.add(item.article.id)
        return latest, ["superseded_analysis_excluded"] if len(latest) != len(candidates) else []

    def _eligible_candidates(self, candidates: list[SignalCandidate]) -> tuple[list[SignalCandidate], list[str]]:
        eligible, codes, seen_hashes = [], [], set()
        for item in candidates:
            if item.link.link_status != "confirmed":
                codes.append("unconfirmed_company_link_excluded")
            elif item.analysis.requires_human_review or item.analysis.review_status != "not_required":
                codes.append("human_review_analysis_excluded")
            elif item.analysis.direction == "unknown":
                codes.append("unknown_direction_excluded")
            elif item.analysis.relevance_score < self.config.min_relevance:
                codes.append("low_relevance_excluded")
            elif item.article.processing_status not in {"processed", "partial"}:
                codes.append("unprocessed_article_excluded")
            elif item.article.content_hash and item.article.content_hash in seen_hashes:
                codes.append("duplicate_content_excluded")
            else:
                eligible.append(item)
                if item.article.content_hash:
                    seen_hashes.add(item.article.content_hash)
        return eligible, self._unique(codes)

    def _coverage(self, sources: list[NewsSource], runs: list[NewsIngestionRun], has_eligible: bool, as_of: datetime) -> tuple[NewsCoverageStatus, list[str], int | None]:
        if not sources:
            return NewsCoverageStatus.UNAVAILABLE, ["no_enabled_sources"], None
        latest_runs: dict[UUID, NewsIngestionRun] = {}
        for run in runs:
            latest_runs.setdefault(run.source_id, run)
        cutoff = as_of - self.config.source_freshness
        states = []
        for source in sources:
            run = latest_runs.get(source.id)
            if run is None:
                states.append(("missing", None))
            elif run.status == "success" and run.finished_at >= cutoff:
                states.append(("fresh", run.finished_at))
            elif run.status == "success":
                states.append(("stale", run.finished_at))
            elif run.status == "partial":
                states.append(("partial", run.finished_at))
            else:
                states.append(("failed", run.finished_at))
        successful = [finished for state, finished in states if state in {"fresh", "stale"} and finished]
        freshness = max(0, int((as_of - max(successful)).total_seconds())) if successful else None
        state_names = {state for state, _ in states}
        if state_names == {"fresh"}:
            return (NewsCoverageStatus.AVAILABLE if has_eligible else NewsCoverageStatus.NO_RELEVANT_NEWS), [], freshness
        if "fresh" in state_names:
            return NewsCoverageStatus.PARTIAL, ["source_coverage_partial"], freshness
        if "stale" in state_names:
            return NewsCoverageStatus.STALE, ["source_coverage_stale"], freshness
        return NewsCoverageStatus.UNAVAILABLE, ["source_coverage_unavailable"], freshness

    @staticmethod
    def _direction(candidates: list[SignalCandidate]) -> tuple[str, list[str]]:
        directions = {item.analysis.direction for item in candidates}
        if not directions:
            return "unknown", ["no_eligible_direction"]
        if len(directions) > 1:
            return "unknown", ["conflicting_directions"]
        return next(iter(directions)), []

    @staticmethod
    def _limitations(coverage: NewsCoverageStatus, codes: list[str]) -> list[str]:
        messages = {
            NewsCoverageStatus.PARTIAL: "One or more enabled sources did not complete successfully.",
            NewsCoverageStatus.STALE: "The latest successful source collection is older than the freshness limit.",
            NewsCoverageStatus.UNAVAILABLE: "No fresh successful collection is available from enabled sources.",
        }
        result = [messages[coverage]] if coverage in messages else []
        if "conflicting_directions" in codes:
            result.append("Eligible articles disagree on direction.")
        return result

    def _input_hash(self, company_id: UUID, as_of: datetime, candidates: list[SignalCandidate], codes: list[str]) -> str:
        payload = {"company_id": str(company_id), "as_of": as_of.isoformat(), "config": self.config.version, "candidates": [{"article": str(item.article.id), "analysis": str(item.analysis.id), "version": item.analysis.analysis_version, "updated": item.analysis.updated_at.isoformat()} for item in candidates], "reason_codes": codes}
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
