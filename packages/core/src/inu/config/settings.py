"""Typed settings schema.

The schema has no operational defaults. Every value comes from config/base.yaml, a
profile file, or an environment variable, so there is one place to look for each
setting. Only secrets are optional, because a fresh clone has none.
"""

from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PositiveInt,
    SecretStr,
    field_validator,
    model_validator,
)
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


class ExporterKind(StrEnum):
    NONE = "none"
    CONSOLE = "console"
    OTLP = "otlp"


class _ExporterSettings(_Section):
    exporter: ExporterKind
    otlp_endpoint: HttpUrl | None = None

    @model_validator(mode="after")
    def _otlp_needs_endpoint(self) -> Self:
        if self.exporter is ExporterKind.OTLP and self.otlp_endpoint is None:
            raise ValueError("otlp_endpoint is required when exporter is 'otlp'")
        return self


class TraceSettings(_ExporterSettings):
    sample_ratio: float = Field(ge=0.0, le=1.0)


class MetricSettings(_ExporterSettings):
    export_interval_ms: int = Field(gt=0)


class TelemetrySettings(_Section):
    service_name: str = Field(min_length=1)
    traces: TraceSettings
    metrics: MetricSettings


class ResampleQuality(StrEnum):
    """soxr quality presets. Higher quality adds streaming delay (see ADR 0006)."""

    QQ = "QQ"
    LQ = "LQ"
    MQ = "MQ"
    HQ = "HQ"
    VHQ = "VHQ"


class AudioDirectionSettings(_Section):
    device: str | None = Field(
        description="Case-insensitive part of the device name; null selects the default."
    )
    sample_rate: PositiveInt | None = Field(description="Null uses the device's native rate.")
    block_ms: int = Field(gt=0, le=100, description="Audio callback period.")
    buffer_ms: int = Field(gt=0, description="Ring buffer length.")

    @model_validator(mode="after")
    def _buffer_holds_several_blocks(self) -> Self:
        if self.buffer_ms < 4 * self.block_ms:
            raise ValueError("buffer_ms must be at least 4 x block_ms")
        return self


class AudioSettings(_Section):
    host_api: str | None = Field(description="e.g. 'Windows WASAPI'; null uses the default.")
    pipeline_sample_rate: PositiveInt = Field(description="Rate VAD and STT consume.")
    frame_ms: PositiveInt = Field(description="Length of each captured frame.")
    resample_quality: ResampleQuality
    reconnect_interval_ms: PositiveInt
    stall_timeout_ms: PositiveInt = Field(description="No callbacks for this long = stream lost.")
    gil_switch_interval_ms: float = Field(
        gt=0, le=5, description="CPython GIL switch interval while audio runs (ADR 0006)."
    )
    input: AudioDirectionSettings
    output: AudioDirectionSettings

    @model_validator(mode="after")
    def _frames_are_whole_samples(self) -> Self:
        if self.pipeline_sample_rate * self.frame_ms % 1000:
            raise ValueError("pipeline_sample_rate x frame_ms must be a multiple of 1000")
        return self


class NetworkSettings(_Section):
    system_trust_store: bool = Field(
        description="Verify TLS against the OS trust store instead of certifi's bundle. "
        "Needed where antivirus or a proxy re-signs HTTPS traffic."
    )
    download_timeout_s: float = Field(gt=0, description="Connect and per-read timeout.")


class ModelAsset(_Section):
    """A model file fetched once from a pinned URL and verified by SHA-256 on download.

    Put the version in `path`, so changing the pin fetches a new file instead of
    trusting an old one.
    """

    path: Path = Field(description="Relative to `data_dir`.")
    url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


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
    data_dir: Path = Field(description="Models and local state. Relative to the working dir.")
    network: NetworkSettings
    log: LogSettings
    telemetry: TelemetrySettings
    audio: AudioSettings
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
