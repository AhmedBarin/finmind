from __future__ import annotations

from app.explanation.glossary import (
    get_indicator_glossary,
    list_indicator_definitions,
)


def test_all_required_terms_have_arabic_and_english_definitions() -> None:
    names = {item.name for item in list_indicator_definitions()}

    assert {
        "RSI14",
        "SMA20",
        "SMA50",
        "SMA200",
        "MACD",
        "ATR14",
        "ATR%",
        "ADX14",
        "Bollinger Bands",
        "Support/Resistance",
        "Volume Ratio",
        "Setup Score",
    } <= names
    assert all(item.explanation_ar and item.explanation_en for item in list_indicator_definitions())


def test_lookup_is_case_and_separator_insensitive() -> None:
    assert get_indicator_glossary("rsi 14") == get_indicator_glossary("RSI14")
    assert get_indicator_glossary("bollinger-bands") == get_indicator_glossary("Bollinger Bands")
    assert get_indicator_glossary("ATR PERCENT") == get_indicator_glossary("ATR%")


def test_setup_score_explains_it_is_not_a_profit_probability() -> None:
    definition = get_indicator_glossary("setup_score")

    assert definition is not None
    assert "احتمالاً للربح" in (definition.note_ar or "")
    assert "not a probability of profit" in (definition.note_en or "")


def test_unknown_or_empty_glossary_name_is_reported_as_missing() -> None:
    assert get_indicator_glossary("unknown indicator") is None
    assert get_indicator_glossary("  ") is None
