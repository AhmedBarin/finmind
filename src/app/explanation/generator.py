"""LangChain model adapter and bounded structured generation."""

from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

from app.explanation.interfaces import LLMClient
from app.explanation.prompts import ExplanationPromptBuilder
from app.explanation.schemas import ExplanationLanguage, ExplanationMode


ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredGenerationError(RuntimeError):
    """Raised when a provider cannot produce the requested structured output."""


class GroqLLMClient:
    """Small LangChain-Groq adapter kept behind the shared LLM protocol."""

    def __init__(self, *, model_name: str, api_key: str | None = None, temperature: float = 0.0) -> None:
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.temperature = temperature

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[ModelT],
        model_name: str | None = None,
    ) -> ModelT:
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:
            raise StructuredGenerationError("LangChain Groq is not installed.") from exc

        if not self.api_key:
            raise StructuredGenerationError("GROQ_API_KEY is not configured.")
        try:
            model = ChatGroq(
                model=model_name or self.model_name,
                api_key=self.api_key,
                temperature=self.temperature,
            ).with_structured_output(output_model)
            result = await model.ainvoke(
                [("system", system_prompt), ("user", user_prompt)]
            )
            return result if isinstance(result, output_model) else output_model.model_validate(result)
        except Exception as exc:
            raise StructuredGenerationError("The LLM returned invalid structured output.") from exc


class StructuredGenerator:
    def __init__(self, llm: LLMClient, prompt_builder: ExplanationPromptBuilder | None = None) -> None:
        self.llm = llm
        self.prompt_builder = prompt_builder or ExplanationPromptBuilder()

    async def generate(
        self,
        *,
        mode: ExplanationMode,
        language: ExplanationLanguage,
        context: str,
        output_model: type[ModelT],
    ) -> ModelT:
        return await self.llm.generate_structured(
            system_prompt=self.prompt_builder.system_prompt(mode, language),
            user_prompt=self.prompt_builder.user_prompt(context=context),
            output_model=output_model,
        )
