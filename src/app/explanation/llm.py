"""Groq-backed implementation of the shared structured LLM protocol."""

from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.config import Settings, settings
from app.explanation.interfaces import LLMClient


ModelT = TypeVar("ModelT", bound=BaseModel)
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class StructuredLLMError(RuntimeError):
    """Safe-to-report error for structured generation failures."""


class GroqStructuredLLMClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str | SecretStr,
        model: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not secret.strip() or not model.strip() or timeout_seconds <= 0:
            raise ValueError("Groq key, model, and positive timeout are required")
        self._api_key = SecretStr(secret)
        self.model_name = model.strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_settings(cls, config: Settings = settings) -> "GroqStructuredLLMClient":
        if config.groq_api_key is None or not config.groq_api_key.get_secret_value().strip():
            raise StructuredLLMError("GROQ_API_KEY is not configured")
        if config.explanation_model is None or not config.explanation_model.strip():
            raise StructuredLLMError("EXPLANATION_MODEL is not configured")
        return cls(api_key=config.groq_api_key, model=config.explanation_model)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[ModelT],
        model_name: str | None = None,
    ) -> ModelT:
        user_content = json.dumps(
            {
                "request": user_prompt,
                "required_output_schema": output_model.model_json_schema(),
            },
            ensure_ascii=False,
        )
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.post(
                    GROQ_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name or self.model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            raise StructuredLLMError("Structured generation timed out") from None
        except httpx.HTTPStatusError as exc:
            raise StructuredLLMError(
                f"Structured generation provider returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.RequestError:
            raise StructuredLLMError("Could not reach the structured generation provider") from None

        try:
            content: Any = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty structured response")
            return output_model.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise StructuredLLMError("Provider returned invalid structured output") from exc
