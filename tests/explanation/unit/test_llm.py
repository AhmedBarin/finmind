from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.explanation.config import ExplanationSettings
from app.explanation.llm import GroqExplanationLLM, ExplanationLLMError


def _generator(handler) -> GroqExplanationLLM:
    return GroqExplanationLLM(
        api_key=SecretStr("k"), model="m", transport=httpx.MockTransport(handler)
    )


def _settings(**kwargs) -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@h/d", _env_file=None, **kwargs)


@pytest.mark.asyncio
async def test_complete_returns_message_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})

    assert await _generator(handler).complete([{"role": "user", "content": "x"}]) == '{"a": 1}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
    ],
)
async def test_complete_raises_safe_error(response):
    with pytest.raises(ExplanationLLMError):
        await _generator(lambda request: response).complete([])


def test_from_settings_needs_key_and_model():
    no_model = ExplanationSettings(_env_file=None)
    assert GroqExplanationLLM.from_settings(_settings(), no_model) is None
    assert GroqExplanationLLM.from_settings(_settings(groq_api_key="k"), no_model) is None

    fallback = GroqExplanationLLM.from_settings(
        _settings(groq_api_key="k", news_analysis_model="news-model"), no_model
    )
    assert fallback is not None and fallback.model_name == "news-model"

    explicit = ExplanationSettings(_env_file=None, llm_model="qa-model")
    chosen = GroqExplanationLLM.from_settings(_settings(groq_api_key="k"), explicit)
    assert chosen is not None and chosen.model_name == "qa-model"
