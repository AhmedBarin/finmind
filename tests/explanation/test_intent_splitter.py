from __future__ import annotations

import pytest

from app.explanation.intent_splitter import QuestionIntent, split_question_intent


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("What is the RSI value?", QuestionIntent.DESCRIPTIVE),
        ("ما قيمة مؤشر RSI؟", QuestionIntent.DESCRIPTIVE),
        ("Should I buy COMI?", QuestionIntent.RECOMMENDATION),
        ("هل أشتري سهم COMI؟", QuestionIntent.RECOMMENDATION),
        ("Explain RSI and should I buy COMI?", QuestionIntent.MIXED),
        ("ما قيمة RSI، وهل أشتري السهم؟", QuestionIntent.MIXED),
        ("Hello there", QuestionIntent.AMBIGUOUS),
    ],
)
def test_classifies_english_and_arabic_questions(
    question: str, intent: QuestionIntent
) -> None:
    result = split_question_intent(question)

    assert result.intent is intent


def test_mixed_question_splits_descriptive_and_recommendation_parts() -> None:
    result = split_question_intent("What is RSI and should I buy COMI?")

    assert result.intent is QuestionIntent.MIXED
    assert result.descriptive_question == "What is RSI"
    assert result.recommendation_question == "should I buy COMI?"


def test_splitter_preserves_ambiguous_clauses_and_does_not_invent_routes() -> None:
    result = split_question_intent("What is RSI and tell me something")

    assert result.intent is QuestionIntent.AMBIGUOUS
    assert result.descriptive_question is None
    assert result.recommendation_question is None


def test_empty_question_is_ambiguous() -> None:
    assert split_question_intent("  ").intent is QuestionIntent.AMBIGUOUS
