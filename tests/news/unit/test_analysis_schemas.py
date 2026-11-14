import pytest
from pydantic import ValidationError

from app.news.analysis_schemas import (
    EvidenceSourceField,
    NewsDirectionLevel,
    NewsSentiment,
    StructuredNewsAnalysis,
    validate_evidence_against_article,
)


def make_valid_analysis(**overrides: object) -> StructuredNewsAnalysis:
    data: dict[str, object] = {
        "event_type": "earnings_results",
        "sentiment": "positive",
        "direction_level": "medium",
        "relevance_score": 0.9,
        "novelty_score": 0.8,
        "confidence": {
            "event_type": 0.95,
            "sentiment": 0.85,
            "direction_level": 0.75,
            "relevance": 0.9,
            "novelty": 0.8,
        },
        "summary_ar": "أعلنت الشركة نمو الإيرادات.",
        "evidence_spans": [
            {
                "claim": "Revenue increased.",
                "quote": "Revenue increased by 12%.",
                "source_field": "body_cleaned",
                "start_char": 0,
                "end_char": 25,
            }
        ],
        "requires_human_review": False,
        "limitations": [],
    }
    data.update(overrides)
    return StructuredNewsAnalysis.model_validate(data)


def test_parses_supported_structured_analysis():
    result = make_valid_analysis()

    assert result.schema_version == "news-analysis-v1"
    assert result.sentiment == NewsSentiment.POSITIVE
    assert result.direction_level == NewsDirectionLevel.MEDIUM
    assert result.evidence_spans[0].source_field == EvidenceSourceField.BODY_CLEANED


def test_unknown_classification_requires_human_review_and_can_have_no_evidence():
    result = make_valid_analysis(
        sentiment="unknown",
        direction_level="unknown",
        event_type="unknown",
        evidence_spans=[],
        requires_human_review=True,
    )

    assert result.sentiment == NewsSentiment.UNKNOWN
    assert result.requires_human_review is True


def test_unknown_classification_without_review_flag_is_rejected():
    with pytest.raises(ValidationError, match="unknown classification must be flagged"):
        make_valid_analysis(
            sentiment="unknown",
            direction_level="unknown",
            evidence_spans=[],
            requires_human_review=False,
        )


def test_mixed_sentiment_is_preserved_as_a_separate_label():
    result = make_valid_analysis(sentiment="mixed")

    assert result.sentiment == NewsSentiment.MIXED
    assert result.direction_level == NewsDirectionLevel.MEDIUM


def test_confidence_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        make_valid_analysis(
            confidence={
                "event_type": 1.01,
                "sentiment": 0.85,
                "direction_level": 0.75,
                "relevance": 0.9,
                "novelty": 0.8,
            }
        )


def test_classified_sentiment_without_evidence_is_rejected():
    with pytest.raises(ValidationError, match="requires at least one evidence span"):
        make_valid_analysis(evidence_spans=[])


def test_extra_impact_or_recommendation_fields_are_rejected():
    with pytest.raises(ValidationError):
        make_valid_analysis(impact_score=0.8)

    with pytest.raises(ValidationError):
        make_valid_analysis(recommendation="buy")


def test_evidence_quote_must_match_article_source_and_offsets():
    analysis = make_valid_analysis()

    validate_evidence_against_article(
        analysis,
        title_original="Quarterly results",
        body_original="Revenue increased by 12%.",
        body_cleaned="Revenue increased by 12%.",
        body_excerpt="Revenue increased by 12%.",
    )

    with pytest.raises(ValueError, match="does not match the referenced article offsets"):
        validate_evidence_against_article(
            analysis,
            title_original="Quarterly results",
            body_original="Revenue increased by 12%.",
            body_cleaned="Revenue increased by 13%.",
            body_excerpt="Revenue increased by 12%.",
        )


def test_evidence_without_offsets_must_be_an_exact_quote():
    analysis = make_valid_analysis(
        evidence_spans=[
            {
                "claim": "Revenue increased.",
                "quote": "Revenue increased by 12%.",
                "source_field": "body_original",
            }
        ]
    )

    with pytest.raises(ValueError, match="does not occur in the referenced article field"):
        validate_evidence_against_article(
            analysis,
            title_original="Quarterly results",
            body_original="Revenue increased by 10%.",
            body_cleaned=None,
            body_excerpt=None,
        )


def test_excerpt_can_be_used_as_evidence_when_that_is_the_stored_content():
    analysis = make_valid_analysis(
        evidence_spans=[
            {
                "claim": "Revenue increased.",
                "quote": "Revenue increased by 12%.",
                "source_field": "body_excerpt",
            }
        ]
    )

    validate_evidence_against_article(
        analysis,
        title_original="Quarterly results",
        body_original=None,
        body_cleaned=None,
        body_excerpt="Revenue increased by 12%.",
    )
