"""Tests for the Q&A Safety & Grounding Engine (REQ-033)."""

from __future__ import annotations

from app.explanation.safety import (
    annotate_data_issues,
    contains_recommendation_language,
    extract_numeric_claims,
    get_correction_prompt,
    get_safe_fallback,
    split_intent,
    validate_grounding,
)

# ═══════════════════════════════════════════════════════════════════════════
# Recommendation language detection
# ═══════════════════════════════════════════════════════════════════════════


class TestRecommendationLanguageDetection:
    def test_detects_arabic_buy(self) -> None:
        assert contains_recommendation_language("يجب عليك شراء السهم") is True

    def test_detects_arabic_sell(self) -> None:
        assert contains_recommendation_language("قم بيع الأسهم فوراً") is True

    def test_detects_arabic_advisory(self) -> None:
        assert contains_recommendation_language("أنصحك بـشراء هذا السهم") is True

    def test_detects_english_buy(self) -> None:
        assert contains_recommendation_language("You should buy this stock") is True

    def test_detects_english_sell(self) -> None:
        assert contains_recommendation_language("I recommend you sell now") is True

    def test_clean_descriptive_text_passes(self) -> None:
        text = "مؤشر RSI حالياً عند 55 مما يشير إلى وضع محايد."
        assert contains_recommendation_language(text) is False

    def test_clean_english_text_passes(self) -> None:
        text = "The RSI is currently at 55 indicating a neutral position."
        assert contains_recommendation_language(text) is False

    def test_detects_hold(self) -> None:
        assert contains_recommendation_language("hold this position") is True

    def test_detects_arabic_hold(self) -> None:
        assert contains_recommendation_language("احتفظ بالسهم") is True


class TestSafeFallback:
    def test_arabic_fallback(self) -> None:
        fb = get_safe_fallback("ar")
        assert "لا يمكنني" in fb
        assert "توصيات" in fb

    def test_english_fallback(self) -> None:
        fb = get_safe_fallback("en")
        assert "cannot provide" in fb

    def test_correction_prompt_arabic(self) -> None:
        prompt = get_correction_prompt("ar")
        assert "توصيات" in prompt

    def test_correction_prompt_english(self) -> None:
        prompt = get_correction_prompt("en")
        assert "recommendation" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# Grounding validation
# ═══════════════════════════════════════════════════════════════════════════


class TestNumericExtraction:
    def test_extracts_integers(self) -> None:
        claims = extract_numeric_claims("RSI is 55 and volume is 1500000")
        assert "55" in claims
        assert "1500000" in claims

    def test_extracts_decimals(self) -> None:
        claims = extract_numeric_claims("SMA-20 is 42.5 EGP")
        assert "42.5" in claims

    def test_extracts_percentages(self) -> None:
        claims = extract_numeric_claims("Score is 72%")
        assert "72" in claims

    def test_empty_text(self) -> None:
        assert extract_numeric_claims("") == []

    def test_no_numbers(self) -> None:
        assert extract_numeric_claims("No numbers here") == []


class TestGroundingValidation:
    def test_grounded_response(self) -> None:
        tool_outputs = [
            {"tool": "technical_snapshot", "snapshot": {"rsi": 55.0, "sma_20": 42.5}},
        ]
        text = "RSI is 55 and SMA-20 is 42.5"
        is_grounded, ungrounded = validate_grounding(text, tool_outputs)
        assert is_grounded is True
        assert ungrounded == []

    def test_ungrounded_response(self) -> None:
        tool_outputs = [
            {"tool": "technical_snapshot", "snapshot": {"rsi": 55.0}},
        ]
        text = "RSI is 55 and the target is 99.9"
        is_grounded, ungrounded = validate_grounding(text, tool_outputs)
        assert is_grounded is False
        assert "99" in ungrounded or "99.9" in ungrounded

    def test_no_numbers_is_grounded(self) -> None:
        is_grounded, ungrounded = validate_grounding("No numbers here", [])
        assert is_grounded is True
        assert ungrounded == []

    def test_numbers_from_nested_data(self) -> None:
        tool_outputs = [
            {
                "tool": "price_history",
                "prices": [{"close": 43.0, "volume": 1500000}],
            },
        ]
        text = "Close price is 43 with volume 1500000"
        is_grounded, _ = validate_grounding(text, tool_outputs)
        assert is_grounded is True


# ═══════════════════════════════════════════════════════════════════════════
# Intent splitting
# ═══════════════════════════════════════════════════════════════════════════


class TestIntentSplitting:
    def test_purely_descriptive(self) -> None:
        desc, adv = split_intent("what is the RSI for COMI?")
        assert desc is not None
        assert adv is None

    def test_purely_advisory(self) -> None:
        desc, adv = split_intent("should i buy COMI?")
        assert desc is None
        assert adv is not None

    def test_mixed_intent(self) -> None:
        desc, adv = split_intent("what is the RSI and should i buy COMI?")
        assert desc is not None
        assert adv is not None

    def test_arabic_descriptive(self) -> None:
        desc, adv = split_intent("ما هو مؤشر القوة النسبية لسهم كوم آي؟")
        assert desc is not None
        assert adv is None

    def test_arabic_advisory(self) -> None:
        desc, adv = split_intent("هل أشتري سهم كوم آي؟")
        assert desc is None
        assert adv is not None

    def test_empty_question(self) -> None:
        desc, adv = split_intent("")
        assert desc is None
        assert adv is None


# ═══════════════════════════════════════════════════════════════════════════
# Data issue annotation
# ═══════════════════════════════════════════════════════════════════════════


class TestDataIssueAnnotation:
    def test_not_found_annotation_ar(self) -> None:
        outputs = [
            {"tool": "technical_snapshot", "ticker": "COMI", "status": "not_found"}
        ]
        issues = annotate_data_issues(outputs, "ar")
        assert len(issues) == 1
        assert "COMI" in issues[0]

    def test_stale_annotation_ar(self) -> None:
        outputs = [
            {
                "tool": "technical_snapshot",
                "ticker": "COMI",
                "status": "stale",
                "data_date": "2026-11-01",
            }
        ]
        issues = annotate_data_issues(outputs, "ar")
        assert len(issues) == 1
        assert "قديمة" in issues[0]

    def test_unavailable_annotation_en(self) -> None:
        outputs = [
            {
                "tool": "price_history",
                "ticker": "COMI",
                "status": "unavailable",
                "error": "timeout",
            }
        ]
        issues = annotate_data_issues(outputs, "en")
        assert len(issues) == 1
        assert "Could not access" in issues[0]
        assert "timeout" in issues[0]

    def test_ok_status_no_issues(self) -> None:
        outputs = [{"tool": "technical_snapshot", "ticker": "COMI", "status": "ok"}]
        issues = annotate_data_issues(outputs, "ar")
        assert len(issues) == 0
