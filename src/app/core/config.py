from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    # Investor Agent LLM extraction (optional). When ``ollama_base_url`` is unset
    # the interview uses the deterministic keyword extractor only.
    ollama_base_url: str | None = None
    investor_llm_model: str = "qwen3.5:4b"
    investor_llm_timeout_seconds: float = 180.0
    # Let reasoning models think before answering (slower, more accurate).
    investor_llm_think: bool = True
    # Ollama context window (tokens). Ollama's default can be huge and spill a
    # large model onto the CPU.
    investor_llm_num_ctx: int = 8192

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
