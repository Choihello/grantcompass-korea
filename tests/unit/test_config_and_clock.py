from datetime import UTC
from pathlib import Path

import pytest

from grantcompass.clock import SystemClock
from grantcompass.config import Settings
from grantcompass.storage.db import DEFAULT_DATABASE_URL


def test_settings_use_safe_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: no environment file at the settings boundary.
    monkeypatch.chdir(tmp_path)
    for name in (
        "GRANTCOMPASS_DATABASE_URL",
        "GRANTCOMPASS_KSTARTUP_SERVICE_KEY",
        "GRANTCOMPASS_BIZINFO_SERVICE_KEY",
        "GRANTCOMPASS_REQUEST_TIMEOUT_SECONDS",
        "GRANTCOMPASS_SOURCE_PAGE_SIZE",
        "GRANTCOMPASS_TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)

    # When: settings are constructed from defaults only.
    settings = Settings()

    # Then: local async storage and non-secret operational defaults are selected.
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.kstartup_service_key is None
    assert settings.bizinfo_service_key is None
    assert settings.request_timeout_seconds == 20.0
    assert settings.source_page_size == 100
    assert settings.timezone == "Asia/Seoul"


def test_system_clock_returns_utc_instant() -> None:
    # Given: the production clock abstraction.
    clock = SystemClock()

    # When: the current instant is requested.
    instant = clock.now()

    # Then: storage-facing time is explicitly UTC-aware.
    assert instant.tzinfo is UTC
