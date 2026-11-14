from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.news.signal_repository import SignalCandidate
from app.news.signal_schemas import NewsCoverageStatus, NewsSignalAggregationConfig
from app.news.signal_service import NewsSignalService


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def candidate(*, direction="positive", relevance=0.9, review=False, link="confirmed", content_hash=None):
    article_id = uuid4()
    return SignalCandidate(
        analysis=SimpleNamespace(id=uuid4(), analysis_version="v1", direction=direction, relevance_score=relevance, requires_human_review=review, review_status="pending" if review else "not_required", event_type="earnings_results", updated_at=NOW),
        article=SimpleNamespace(id=article_id, content_hash=content_hash, processing_status="processed"),
        link=SimpleNamespace(link_status=link),
    )


def source(source_id, *, status="success", finished_at=NOW - timedelta(hours=1)):
    return SimpleNamespace(id=source_id, source_key="source", enabled=True), SimpleNamespace(source_id=source_id, status=status, finished_at=finished_at)


def test_conflicting_eligible_directions_become_unknown_without_a_score():
    direction, codes = NewsSignalService._direction([candidate(direction="positive"), candidate(direction="negative")])

    assert direction == "unknown"
    assert codes == ["conflicting_directions"]


def test_eligibility_excludes_unknown_reviewed_low_relevance_unconfirmed_and_duplicates():
    service = NewsSignalService(config=NewsSignalAggregationConfig(min_relevance=0.5))
    eligible, codes = service._eligible_candidates([
        candidate(content_hash="same"), candidate(content_hash="same"), candidate(direction="unknown"),
        candidate(review=True), candidate(relevance=0.2), candidate(link="candidate"),
    ])

    assert len(eligible) == 1
    assert set(codes) == {"duplicate_content_excluded", "unknown_direction_excluded", "human_review_analysis_excluded", "low_relevance_excluded", "unconfirmed_company_link_excluded"}


@pytest.mark.parametrize(("statuses", "has_eligible", "expected"), [
    (["success"], True, NewsCoverageStatus.AVAILABLE),
    (["success"], False, NewsCoverageStatus.NO_RELEVANT_NEWS),
    (["success", "failed"], True, NewsCoverageStatus.PARTIAL),
    (["success"], False, NewsCoverageStatus.STALE),
    (["failed"], False, NewsCoverageStatus.UNAVAILABLE),
])
def test_coverage_preserves_no_news_stale_partial_and_unavailable_states(statuses, has_eligible, expected):
    service = NewsSignalService()
    sources, runs = [], []
    for index, status in enumerate(statuses):
        source_id = uuid4()
        finished_at = NOW - timedelta(days=2) if expected == NewsCoverageStatus.STALE else NOW - timedelta(hours=1)
        source_row, run = source(source_id, status=status, finished_at=finished_at)
        sources.append(source_row)
        runs.append(run)
    coverage, _, _ = service._coverage(sources, runs, has_eligible, NOW)
    assert coverage == expected


def test_naive_as_of_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        NewsSignalService._as_utc(datetime(2026, 11, 13, 12))
