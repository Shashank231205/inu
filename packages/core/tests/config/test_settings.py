from pathlib import Path

import pytest

from inu.config import ConfigError, load_settings


def _cloud_profile(repo_config_dir: Path, tmp_path: Path) -> Path:
    """Copy of the shipped config with a profile that turns cloud LLMs on."""
    root = tmp_path / "config"
    (root / "profiles").mkdir(parents=True)
    (root / "base.yaml").write_bytes((repo_config_dir / "base.yaml").read_bytes())
    (root / "profiles" / "cloud.yaml").write_text("features: {cloud_llm: true}\n", "utf-8")
    return root


def test_cloud_llm_without_any_key_fails_fast(repo_config_dir: Path, tmp_path: Path) -> None:
    root = _cloud_profile(repo_config_dir, tmp_path)
    with pytest.raises(ConfigError, match="cloud_llm is enabled but no provider key"):
        load_settings(profile="cloud", config_dir=root)


def test_cloud_llm_with_one_key_is_accepted(
    repo_config_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _cloud_profile(repo_config_dir, tmp_path)
    monkeypatch.setenv("INU_SECRETS__GEMINI_API_KEY", "key-value")
    settings = load_settings(profile="cloud", config_dir=root)
    assert settings.secrets.has_cloud_key()


def test_blank_secret_counts_as_unset(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INU_SECRETS__GROQ_API_KEY", "")
    settings = load_settings(profile="laptop", config_dir=repo_config_dir)
    assert settings.secrets.groq_api_key is None


def test_secrets_are_redacted_everywhere_they_could_leak(
    repo_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INU_SECRETS__GROQ_API_KEY", "gsk_super_secret")
    settings = load_settings(profile="laptop", config_dir=repo_config_dir)

    assert "gsk_super_secret" not in repr(settings)
    assert "gsk_super_secret" not in str(settings.model_dump(mode="json"))
    assert settings.secrets.groq_api_key is not None
    assert settings.secrets.groq_api_key.get_secret_value() == "gsk_super_secret"


def test_settings_are_immutable(repo_config_dir: Path) -> None:
    settings = load_settings(profile="laptop", config_dir=repo_config_dir)
    with pytest.raises(ValueError, match="frozen"):
        settings.instance_name = "changed"  # type: ignore[misc]
