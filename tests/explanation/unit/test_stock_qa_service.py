from __future__ import annotations

from datetime import date

import pytest

from app.explanation.stock_qa.schemas import StockQARequest
from app.explanation.stock_qa.service import (
    DISCLAIMER_AR,
    NO_LLM_NOTE_AR,
    ROUTED_NOTE_AR,
    StockQAService,
)
from tests.explanation.unit.conftest import (
    GOOD_ANSWER,
    GOOD_FACTS,
    TODAY,
    FakeTools,
    ScriptedGenerator,
    draft,
    make_snapshot,
)

pytestmark = pytest.mark.asyncio


def _service(generator=None, **kwargs) -> StockQAService:
    return StockQAService(generator, today=lambda: TODAY, **kwargs)


def _request(question="ما قيمة مؤشر القوة النسبية؟", tickers=("COMI.CA",), **kwargs) -> StockQARequest:
    return StockQARequest(question=question, tickers=list(tickers), **kwargs)


def _tools(*tickers: str) -> FakeTools:
    return FakeTools({t: make_snapshot(t) for t in tickers or ("COMI.CA",)})


async def test_valid_draft_is_returned_with_required_fields():
    generator = ScriptedGenerator(draft(GOOD_ANSWER, GOOD_FACTS))
    response = await _service(generator).answer(_tools(), _request())

    assert response.generation == "llm"
    assert response.explanation_type == "stock_qa"
    assert response.tickers == ["COMI.CA"]
    assert response.data_date == date(2026, 11, 16)
    assert response.answer_ar == GOOD_ANSWER
    assert response.facts[0].value == pytest.approx(56.2347)
    assert response.disclaimer_ar == DISCLAIMER_AR
    assert response.freshness[0].status == "fresh"
    assert "get_technical_snapshot" in response.tools_used
    assert "get_indicator_glossary" in response.tools_used  # question names RSI


async def test_prompt_excludes_raw_input_window():
    generator = ScriptedGenerator(draft(GOOD_ANSWER, GOOD_FACTS))
    await _service(generator).answer(_tools(), _request())
    user_payload = generator.calls[0][1]["content"]
    assert "999.99" not in user_payload
    assert "source_window" not in user_payload


async def test_ungrounded_number_triggers_one_retry():
    bad = draft("بتاريخ 2026-11-16 ارتفع السهم بنسبة 3.5%.")
    generator = ScriptedGenerator(bad, draft(GOOD_ANSWER, GOOD_FACTS))
    response = await _service(generator).answer(_tools(), _request())

    assert response.generation == "llm_retry"
    assert len(generator.calls) == 2
    retry_prompt = generator.calls[1][-1]["content"]
    assert "3.5" in retry_prompt


async def test_recommendation_language_twice_falls_back_to_template():
    bad = draft("بتاريخ 2026-11-16 ننصح بشراء السهم.")
    generator = ScriptedGenerator(bad, bad)
    response = await _service(generator).answer(_tools(), _request())

    assert response.generation == "fallback"
    assert "2026-11-16" in response.answer_ar
    assert "56.23" in response.answer_ar
    assert {f.field for f in response.facts} >= {"rsi", "sma_20", "regime", "risk_label"}
    assert "ننصح" not in response.answer_ar


async def test_invalid_json_twice_falls_back():
    generator = ScriptedGenerator("not json", '{"answer": "wrong shape"}')
    response = await _service(generator).answer(_tools(), _request())
    assert response.generation == "fallback"
    assert "output_schema" in generator.calls[1][-1]["content"]


async def test_generator_error_falls_back_without_retry(generation_error):
    generator = ScriptedGenerator(generation_error)
    response = await _service(generator).answer(_tools(), _request())
    assert response.generation == "fallback"
    assert len(generator.calls) == 1


async def test_no_generator_uses_template_and_says_so():
    response = await _service(None).answer(_tools(), _request())
    assert response.generation == "fallback"
    assert NO_LLM_NOTE_AR in response.limitations_ar


async def test_answer_must_state_data_date():
    no_date = draft("مؤشر القوة النسبية لسهم COMI.CA نحو 56.2.")
    generator = ScriptedGenerator(no_date, no_date)
    response = await _service(generator).answer(_tools(), _request())
    assert response.generation == "fallback"
    assert "YYYY-MM-DD" in generator.calls[1][-1]["content"]


async def test_fact_for_unrequested_ticker_is_rejected():
    facts = [{"ticker": "HRHO.CA", "field": "rsi", "value": 56.2347}]
    generator = ScriptedGenerator(draft(GOOD_ANSWER, facts), draft(GOOD_ANSWER, facts))
    response = await _service(generator).answer(_tools(), _request())
    assert response.generation == "fallback"
    assert "HRHO.CA" in generator.calls[1][-1]["content"]


async def test_fact_with_unknown_date_is_rejected():
    facts = [{"ticker": "COMI.CA", "field": "rsi", "value": 56.2347, "data_date": "2026-01-01"}]
    generator = ScriptedGenerator(draft(GOOD_ANSWER, facts), draft(GOOD_ANSWER, GOOD_FACTS))
    response = await _service(generator).answer(_tools(), _request())
    assert response.generation == "llm_retry"


async def test_pure_recommendation_question_is_routed_without_tools():
    tools = _tools()
    generator = ScriptedGenerator()
    response = await _service(generator).answer(tools, _request("هل أشتري السهم؟"))

    assert response.generation == "routed_only"
    assert response.routed_to_recommendation == ["هل أشتري السهم"]
    assert tools.calls == []
    assert generator.calls == []


async def test_mixed_question_answers_descriptive_part_and_routes_the_rest():
    generator = ScriptedGenerator(draft(GOOD_ANSWER, GOOD_FACTS))
    response = await _service(generator).answer(
        _tools(), _request("ما قيمة مؤشر القوة النسبية وهل أشتري السهم؟")
    )
    assert response.generation == "llm"
    assert response.routed_to_recommendation == ["وهل أشتري السهم"]
    assert ROUTED_NOTE_AR in response.limitations_ar
    assert "أشتري" not in generator.calls[0][1]["content"]


async def test_missing_data_for_all_tickers_returns_no_data():
    generator = ScriptedGenerator()
    response = await _service(generator).answer(FakeTools({}), _request())
    assert response.generation == "no_data"
    assert response.data_date is None
    assert response.freshness[0].status == "missing"
    assert generator.calls == []
    assert any("COMI.CA" in note for note in response.limitations_ar)


async def test_partial_missing_ticker_is_reported():
    tools = _tools("COMI.CA")
    generator = ScriptedGenerator(draft(GOOD_ANSWER, GOOD_FACTS))
    response = await _service(generator).answer(tools, _request(tickers=("COMI.CA", "HRHO.CA")))
    statuses = {f.ticker: f.status for f in response.freshness}
    assert statuses == {"COMI.CA": "fresh", "HRHO.CA": "missing"}
    assert any("HRHO.CA" in note for note in response.limitations_ar)
    assert "compare_snapshots" in response.tools_used


async def test_old_snapshot_is_stale():
    tools = FakeTools({"COMI.CA": make_snapshot(day=date(2026, 11, 1))})
    answer = "بتاريخ 2026-11-01 بلغ مؤشر القوة النسبية 56.2."
    generator = ScriptedGenerator(draft(answer))
    response = await _service(generator, max_snapshot_age_days=4).answer(tools, _request())
    assert response.freshness[0].status == "stale"
    assert any("2026-11-01" in note for note in response.limitations_ar)


async def test_engine_stale_flag_is_respected_even_when_recent():
    tools = FakeTools({"COMI.CA": make_snapshot(data_quality_status="stale")})
    response = await _service(None).answer(tools, _request())
    assert response.freshness[0].status == "stale"


async def test_historical_as_of_question_is_not_age_stale():
    tools = FakeTools({"COMI.CA": make_snapshot(day=date(2026, 1, 5))})
    response = await _service(None).answer(tools, _request(as_of=date(2026, 1, 5)))
    assert response.freshness[0].status == "fresh"


async def test_flagged_quality_is_reported():
    tools = FakeTools({"COMI.CA": make_snapshot(data_quality_status="flagged")})
    response = await _service(None).answer(tools, _request())
    assert any("flagged" in note for note in response.limitations_ar)


async def test_indicator_window_numbers_are_allowed():
    answer = "بتاريخ 2026-11-16 كان المتوسط المتحرك SMA 20 عند 81.46."
    generator = ScriptedGenerator(draft(answer))
    response = await _service(generator).answer(_tools(), _request("ما قيمة المتوسط المتحرك؟"))
    assert response.generation == "llm"


async def test_numbers_from_the_question_do_not_ground_a_claim():
    # The user asserts a value; the model must not confirm it without tool data.
    echo = draft("بتاريخ 2026-11-16 نعم، مؤشر القوة النسبية عند 90.")
    generator = ScriptedGenerator(echo, echo)
    response = await _service(generator).answer(
        _tools(), _request("مؤشر القوة النسبية عند 90، صحيح؟")
    )
    assert response.generation == "fallback"
    assert "90" in generator.calls[1][-1]["content"]
