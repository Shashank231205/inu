"""Typed settings schema.

The schema has no operational defaults. Every value comes from config/base.yaml, a
profile file, or an environment variable, so there is one place to look for each
setting. Only secrets are optional, because a fresh clone has none.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LogSettings(_Section):
    level: LogLevel
    format: LogFormat


class FeatureFlags(_Section):
    private_mode: bool = Field(description="Keep every request on this machine (FR-B3).")
    cloud_llm: bool = Field(description="Allow routing requests to cloud LLM providers.")


class ProviderSecrets(_Section):
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # Secret files carry every key, some left blank until the account exists.
        return None if value == "" else value

    def has_cloud_key(self) -> bool:
        return any(
            key is not None
            for key in (self.groq_api_key, self.gemini_api_key, self.openrouter_api_key)
        )


class Settings(BaseSettings):
    """Effective configuration for one INU process.

    Precedence, highest first: environment variables, .env file, secrets directory,
    then the YAML layers passed to the constructor by `load_settings`.
    """

    model_config = SettingsConfigDict(
        env_prefix="INU_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    profile: str = Field(min_length=1)
    instance_name: str = Field(min_length=1, description="Identifies this device in traces.")
    log: LogSettings
    features: FeatureFlags
    secrets: ProviderSecrets = ProviderSecrets()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Constructor kwargs carry the YAML layers, so they rank lowest.
        return env_settings, dotenv_settings, file_secret_settings, init_settings

    @model_validator(mode="after")
    def _cloud_needs_a_key(self) -> Self:
        if self.features.cloud_llm and not self.secrets.has_cloud_key():
            raise ValueError(
                "features.cloud_llm is enabled but no provider key is set; "
                "add one to the secrets file or disable the flag"
            )
        return self
