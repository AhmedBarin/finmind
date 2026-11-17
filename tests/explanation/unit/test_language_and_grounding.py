from __future__ import annotations

import pytest

from app.explanation.stock_qa.grounding import (
    collect_numbers,
    extract_numbers,
    is_grounded,
    ungrounded_numbers,
)
from app.explanation.stock_qa.language import (
    asks_for_recommendation,
    find_recommendation_language,
    split_question,
)


@pytest.mark.parametrize(
    "text",
    [
        "ننصح بشراء السهم الآن",
        "هذه فرصة شراء جيدة",
        "أنصحك بالاحتفاظ بالسهم",
        "يُوصي المحلل بالبيع",
        "You should buy this stock",
        "اشترِ السهم",
        "يمكن وضع وقف الخسارة عند هذا المستوى",
    ],
)
def test_recommendation_language_detected(text):
    assert find_recommendation_language(text)


@pytest.mark.parametrize(
    "text",
    [
        "يظهر السهم ضغطًا بيعيًا خلال الجلسات الأخيرة",
        "مؤشر القوة النسبية عند 56.2 بتاريخ 2026-11-16",
        "هذه المعلومات ليست توصية استثمارية",
        "حالة السوق اتجاه واضح وتصنيف المخاطر متوسط",
    ],
)
def test_descriptive_text_is_clean(text):
    assert find_recommendation_language(text) == []


@pytest.mark.parametrize(
    "question",
    ["هل أشتري سهم التجاري الدولي؟", "Should I buy COMI?", "هل تنصحني بالسهم", "هل يستحق السهم الشراء"],
)
def test_advice_questions(question):
    assert asks_for_recommendation(question)


@pytest.mark.parametrize(
    "question",
    ["ما قيمة مؤشر القوة النسبية؟", "كيف تغير حجم التداول؟", "What is the RSI of COMI?"],
)
def test_descriptive_questions(question):
    assert not asks_for_recommendation(question)


def test_mixed_question_is_split():
    descriptive, advice = split_question("ما قيمة مؤشر القوة النسبية للسهم وهل أشتريه؟")
    assert descriptive == ["ما قيمة مؤشر القوة النسبية للسهم"]
    assert advice == ["وهل أشتريه"]


def test_split_on_question_marks():
    descriptive, advice = split_question("ما هو ATR؟ هل أبيع السهم؟")
    assert descriptive == ["ما هو ATR"]
    assert advice == ["هل أبيع السهم"]


def test_extract_numbers_handles_arabic_digits_and_separators():
    assert extract_numbers("بلغ ٥٦٫٢ وحجم 1,250,000 و٣٠") == ["56.2", "1250000", "30"]


def test_collect_numbers_walks_nested_values_and_strings():
    numbers = collect_numbers({"a": 1.5, "b": [2, {"c": "2026-11-16"}], "flag": True})
    assert numbers == {1.5, 2.0, 2026.0, 11.0, 16.0}


@pytest.mark.parametrize(
    ("written", "expected"),
    [("56.2347", True), ("56.23", True), ("56.2", True), ("56", True), ("57", False), ("56.3", False)],
)
def test_is_grounded_respects_written_precision(written, expected):
    assert is_grounded(written, {56.2347}) is expected


def test_half_way_values_accept_either_rounding():
    assert is_grounded("56.3", {56.25})
    assert is_grounded("56.2", {56.25})


def test_derived_numbers_are_ungrounded():
    # 3.5% is a change the model computed itself, not a stored value.
    assert ungrounded_numbers("ارتفع السهم 3.5% إلى 82.15", {82.15}) == ["3.5"]
