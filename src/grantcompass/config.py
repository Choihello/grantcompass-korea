"""Environment-backed GrantCompass settings boundary."""

from typing import ClassVar

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from grantcompass.storage.db import DEFAULT_DATABASE_URL


class Settings(BaseSettings):
    """Validated operational settings loaded from GrantCompass environment names."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_prefix="GRANTCOMPASS_",
        extra="ignore",
    )

    database_url: str = DEFAULT_DATABASE_URL
    kstartup_service_key: SecretStr | None = None
    bizinfo_service_key: SecretStr | None = None
    request_timeout_seconds: float = Field(default=20.0, gt=0)
    source_page_size: int = Field(default=100, gt=0)
    timezone: str = "Asia/Seoul"
