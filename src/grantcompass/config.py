"""Environment-backed GrantCompass settings boundary."""

from typing import ClassVar

from pydantic import Field, SecretStr, field_validator
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
    allowed_hosts: tuple[str, ...] = Field(
        default=("localhost", "127.0.0.1"),
        min_length=1,
    )
    allowed_origins: tuple[str, ...] = Field(
        default=(
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ),
        min_length=1,
    )
    csrf_signing_secret: SecretStr | None = Field(default=None, min_length=32)

    @field_validator("allowed_hosts", "allowed_origins")
    @classmethod
    def _reject_wildcards(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any("*" in value for value in values):
            message = "wildcard_not_allowed"
            raise ValueError(message)
        return values
