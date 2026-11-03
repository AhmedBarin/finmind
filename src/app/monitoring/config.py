from pydantic_settings import BaseSettings, SettingsConfigDict


class MonitoringSettings(BaseSettings):
    lock_id: int = 4815162342
    max_staleness_hours: int = 36
    default_cooldown_minutes: int = 60
    schedule_cron: str = "30 15 * * 0-4"

    model_config = SettingsConfigDict(
        env_prefix="MONITORING_",
        env_file=".env",
        extra="ignore",
    )


monitoring_settings = MonitoringSettings()
