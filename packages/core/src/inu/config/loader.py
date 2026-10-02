"""Build `Settings` from layered YAML files and the environment.

Layers, lowest to highest priority:
    1. <config_dir>/base.yaml
    2. <config_dir>/profiles/<profile>.yaml
    3. secrets directory (one file per key), if INU_SECRETS_DIR is set
    4. .env in the working directory
    5. INU_* environment variables
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from inu.config.settings import Settings

PROFILE_ENV = "INU_PROFILE"
CONFIG_DIR_ENV = "INU_CONFIG_DIR"
SECRETS_DIR_ENV = "INU_SECRETS_DIR"  # pragma: allowlist secret (variable name)
DEFAULT_CONFIG_DIR = Path("config")


class ConfigError(Exception):
    """Configuration is missing or invalid. The message is meant for humans."""


def load_settings(
    *,
    profile: str | None = None,
    config_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    env = os.environ if environ is None else environ
    config_dir = config_dir or Path(env.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR))
    profile = profile or env.get(PROFILE_ENV)
    if not profile:
        raise ConfigError(
            f"{PROFILE_ENV} is not set. Available profiles: {_list_profiles(config_dir)}"
        )

    profile_file = config_dir / "profiles" / f"{profile}.yaml"
    if not profile_file.is_file():
        raise ConfigError(
            f"Unknown profile {profile!r}. Available profiles: {_list_profiles(config_dir)}"
        )

    layered = deep_merge(_read_yaml(config_dir / "base.yaml"), _read_yaml(profile_file))
    layered["profile"] = profile

    secrets_dir = env.get(SECRETS_DIR_ENV)
    try:
        if secrets_dir:
            return Settings(_secrets_dir=secrets_dir, **layered)
        return Settings(**layered)
    except ValidationError as exc:
        raise ConfigError(_describe(exc, profile)) from exc


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge mappings recursively. Values in `override` win; lists are replaced whole."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _list_profiles(config_dir: Path) -> str:
    names = sorted(p.stem for p in (config_dir / "profiles").glob("*.yaml"))
    return ", ".join(names) or f"none found in {config_dir / 'profiles'}"


def _describe(exc: ValidationError, profile: str) -> str:
    # Input values are left out on purpose: they may be secrets.
    lines = [f"Invalid configuration for profile {profile!r}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"  - {location}: {error['msg']}")
    return "\n".join(lines)
