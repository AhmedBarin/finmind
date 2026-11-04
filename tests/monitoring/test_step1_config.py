import pytest

from app.monitoring.config import MonitoringSettings


class TestMonitoringSettingsDefaults:
    """Verify MonitoringSettings loads correct default values."""

    def test_default_lock_id(self) -> None:
        settings = MonitoringSettings()
        assert settings.lock_id == 4815162342

    def test_default_max_staleness_hours(self) -> None:
        settings = MonitoringSettings()
        assert settings.max_staleness_hours == 36

    def test_default_cooldown_minutes(self) -> None:
        settings = MonitoringSettings()
        assert settings.default_cooldown_minutes == 60

    def test_default_schedule_cron(self) -> None:
        settings = MonitoringSettings()
        assert settings.schedule_cron == "30 15 * * 0-4"


class TestMonitoringSettingsEnvOverrides:
    """Verify MonitoringSettings reads overrides from environment variables."""

    def test_env_override_lock_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONITORING_LOCK_ID", "9999")
        settings = MonitoringSettings()
        assert settings.lock_id == 9999

    def test_env_override_max_staleness_hours(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MONITORING_MAX_STALENESS_HOURS", "72")
        settings = MonitoringSettings()
        assert settings.max_staleness_hours == 72

    def test_env_override_default_cooldown_minutes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MONITORING_DEFAULT_COOLDOWN_MINUTES", "120")
        settings = MonitoringSettings()
        assert settings.default_cooldown_minutes == 120

    def test_env_override_schedule_cron(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONITORING_SCHEDULE_CRON", "0 9 * * 1-5")
        settings = MonitoringSettings()
        assert settings.schedule_cron == "0 9 * * 1-5"


class TestMonitoringSettingsSingleton:
    """Verify the module-level singleton is properly exported."""

    def test_singleton_is_monitoring_settings_instance(self) -> None:
        from app.monitoring.config import monitoring_settings

        assert isinstance(monitoring_settings, MonitoringSettings)
