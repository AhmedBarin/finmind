"""Async Groq chat-completions client for structured news analysis."""

import json
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.news.analysis_prompt import SYSTEM_PROMPT
from app.news.analysis_schemas import StructuredNewsAnalysis


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqAnalysisError(RuntimeError):
    """Safe-to-report error raised for Groq request or response failures."""


class GroqAnalysisClient:
    def __init__(
        self,
        *,
        api_key: str | SecretStr,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if isinstance(api_key, SecretStr):
            api_key = api_key.get_secret_value()
        if not api_key.strip():
            raise ValueError("Groq API key must not be empty")
        if not model.strip():
            raise ValueError("Groq model ID must not be empty")

        self._api_key = SecretStr(api_key)
        self.model_name = model.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(cls, config: Settings = settings) -> "GroqAnalysisClient":
        api_key = config.groq_api_key
        model = config.news_analysis_model
        if api_key is None or not api_key.get_secret_value().strip():
            raise GroqAnalysisError("GROQ_API_KEY is not configured")
        if model is None or not model.strip():
            raise GroqAnalysisError("NEWS_ANALYSIS_MODEL is not configured")
        return cls(api_key=api_key, model=model)

    async def analyze(
        self,
        *,
        article_fields: dict[str, str],
        language: str,
        company_context: dict[str, Any] | None,
        published_at: str | None,
    ) -> StructuredNewsAnalysis:
        user_content = json.dumps(
            {
                "language": language,
                "published_at": published_at,
                "company_context": company_context,
                "article_fields": article_fields,
                "output_schema": StructuredNewsAnalysis.model_json_schema(),
            },
            ensure_ascii=False,
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            for attempt in range(2):
                content = ""
                try:
                    response = await client.post(
                        GROQ_CHAT_COMPLETIONS_URL,
                        headers=headers,
                        json={
                            "model": self.model_name,
                            "messages": messages,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    raise GroqAnalysisError(
                        f"Groq returned HTTP {status} while analyzing the article"
                    ) from None
                except httpx.TimeoutException:
                    raise GroqAnalysisError("Groq analysis request timed out") from None
                except httpx.RequestError:
                    raise GroqAnalysisError("Could not reach the Groq API") from None

                try:
                    payload = response.json()
                    raw_content = payload["choices"][0]["message"]["content"]
                    if not isinstance(raw_content, str) or not raw_content.strip():
                        raise ValueError("Groq returned an empty message")
                    content = raw_content
                    return StructuredNewsAnalysis.model_validate_json(content)
                except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
                    if attempt == 1:
                        raise GroqAnalysisError(
                            "Groq returned invalid structured analysis after one retry"
                        ) from exc
                    messages.extend(
                        [
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": (
                                    "Your previous output failed validation. Return a corrected JSON object "
                                    "matching the required schema. Validation issue: "
                                    f"{type(exc).__name__}. Do not add any fields."
                                ),
                            },
                        ]
                    )

        raise GroqAnalysisError("Groq analysis did not produce a result")
