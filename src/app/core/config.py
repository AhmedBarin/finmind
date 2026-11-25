from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    groq_api_key: SecretStr | None = None
    explanation_model: str | None = None
    news_analysis_model: str | None = None
    news_agent_api_token: SecretStr | None = None
    news_agent_rate_limit_per_minute: int = 30
    explanation_rate_limit_per_minute: int = 30
    news_vector_store_path: str = "./data/chroma"
    news_vector_collection: str = "finmind_news"

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
