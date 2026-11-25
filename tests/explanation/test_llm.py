from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.explanation.llm import GroqStructuredLLMClient, StructuredLLMError


class ExampleOutput(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_groq_structured_client_uses_separate_system_and_user_messages():
    observed = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers["Authorization"]
        body = json.loads(request.content)
        observed["messages"] = body["messages"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"grounded"}'}}]},
        )

    client = GroqStructuredLLMClient(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate_structured(
        system_prompt="trusted instruction",
        user_prompt="untrusted user data",
        output_model=ExampleOutput,
    )

    assert result.answer == "grounded"
    assert observed["authorization"] == "Bearer test-key"
    assert observed["messages"][0] == {"role": "system", "content": "trusted instruction"}
    user_message = json.loads(observed["messages"][1]["content"])
    assert user_message["request"] == "untrusted user data"
    assert user_message["required_output_schema"] == ExampleOutput.model_json_schema()


@pytest.mark.asyncio
async def test_groq_structured_client_rejects_invalid_model_output():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"wrong":"field"}'}}]},
        )

    client = GroqStructuredLLMClient(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(StructuredLLMError, match="invalid structured output"):
        await client.generate_structured(
            system_prompt="trusted",
            user_prompt="data",
            output_model=ExampleOutput,
        )


def test_groq_client_requires_explanation_specific_configuration():
    config = Settings(
        database_url="postgresql+asyncpg://localhost/test",
        groq_api_key="key",
        explanation_model=None,
    )

    with pytest.raises(StructuredLLMError, match="EXPLANATION_MODEL"):
        GroqStructuredLLMClient.from_settings(config)
