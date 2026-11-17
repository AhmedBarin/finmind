"""LLM access for Stock Q&A: a minimal chat interface plus a Groq implementation."""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import SecretStr

from app.core.config import Settings, settings as app_settings
from app.explanation.config import ExplanationSettings, get_explanation_settings
from app.news.groq_client import GROQ_CHAT_COMPLETIONS_URL


class StockQAGenerationError(RuntimeError):
    """The LLM could not be reached or returned no content. Safe to log."""


class StockQAGenerator(Protocol):
    model_name: str

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the raw JSON string produced for ``messages``."""
        ...


class GroqStockQAGenerator:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model_name = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(
        cls,
        config: Settings = app_settings,
        explanation: ExplanationSettings | None = None,
    ) -> GroqStockQAGenerator | None:
        """Build from settings, or return ``None`` when Groq is not configured."""
        explanation = explanation or get_explanation_settings()
        model = (explanation.llm_model or config.news_analysis_model or "").strip()
        key = config.groq_api_key
        if not model or key is None or not key.get_secret_value().strip():
            return None
        return cls(api_key=key, model=model, timeout_seconds=explanation.llm_timeout_seconds)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    GROQ_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model_name,
                        "messages": messages,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise StockQAGenerationError(
                f"Groq returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.TimeoutException:
            raise StockQAGenerationError("Groq request timed out") from None
        except httpx.RequestError:
            raise StockQAGenerationError("Could not reach the Groq API") from None

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise StockQAGenerationError("Groq returned an unexpected payload") from None
        if not isinstance(content, str) or not content.strip():
            raise StockQAGenerationError("Groq returned an empty message")
        return content
