from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    groq_api_key: SecretStr | None = None
    news_analysis_model: str | None = None
    news_agent_api_token: SecretStr | None = None
    news_agent_rate_limit_per_minute: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
