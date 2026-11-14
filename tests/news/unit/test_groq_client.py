import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.news.analysis_schemas import StructuredNewsAnalysis
from app.news.groq_client import GroqAnalysisClient, GroqAnalysisError


def valid_analysis_payload() -> dict[str, object]:
    return {
        "event_type": "earnings_results",
        "direction": "positive",
        "relevance_score": 0.9,
        "novelty_score": 0.8,
        "confidence": {
            "event_type": 0.95,
            "direction": 0.85,
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


@pytest.mark.asyncio
async def test_groq_client_requests_json_and_parses_the_analysis_contract():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_analysis_payload(),
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    client = GroqAnalysisClient(
        api_key="test-secret",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await client.analyze(
        article_fields={"title_original": "Quarterly results"},
        language="en",
        company_context={"ticker": "COMI", "link_status": "confirmed"},
        published_at=None,
    )

    assert result.direction == "positive"
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    contract = captured["body"]["messages"][1]["content"]
    assert '"output_schema"' in contract
    assert '"positive"' in contract
    assert '"earnings_results"' in contract


@pytest.mark.asyncio
async def test_groq_client_retries_once_after_schema_validation_failure():
    requests: list[dict[str, object]] = []
    responses = [
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"direction":"sideways"}'}}]},
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_analysis_payload(),
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return responses.pop(0)

    client = GroqAnalysisClient(
        api_key="test-secret",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await client.analyze(
        article_fields={"title_original": "Quarterly results"},
        language="en",
        company_context={"ticker": "COMI", "link_status": "confirmed"},
        published_at=None,
    )

    assert result.direction == "positive"
    assert len(requests) == 2
    assert "corrected JSON object" in requests[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_groq_client_does_not_include_api_key_in_http_errors():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="request rejected")

    client = GroqAnalysisClient(
        api_key="do-not-leak-this",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GroqAnalysisError, match="HTTP 401") as exc_info:
        await client.analyze(
            article_fields={"title_original": "Quarterly results"},
            language="en",
            company_context=None,
            published_at=None,
        )

    assert "do-not-leak-this" not in str(exc_info.value)


def test_groq_client_requires_local_credentials_and_model_configuration():
    with pytest.raises(GroqAnalysisError, match="GROQ_API_KEY"):
        GroqAnalysisClient.from_settings(
            Settings(
                database_url="postgresql+asyncpg://unused",
                groq_api_key=None,
                news_analysis_model="test-model",
            )
        )

    with pytest.raises(GroqAnalysisError, match="NEWS_ANALYSIS_MODEL"):
        GroqAnalysisClient.from_settings(
            Settings(
                database_url="postgresql+asyncpg://unused",
                groq_api_key=SecretStr("test-secret"),
                news_analysis_model=None,
            )
        )


def test_client_exposes_model_id_without_exposing_secret():
    client = GroqAnalysisClient(api_key="test-secret", model="groq-model")

    assert client.model_name == "groq-model"
    assert "test-secret" not in repr(client._api_key)
