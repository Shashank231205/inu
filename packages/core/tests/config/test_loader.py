from collections.abc import Callable
from pathlib import Path

import pytest

from inu.config import ConfigError, LogFormat, LogLevel, load_settings
from inu.config.loader import deep_merge

MakeConfigDir = Callable[[str, dict[str, str]], Path]

BASE = """\
instance_name: base
log: {level: INFO, format: json}
features: {private_mode: false, cloud_llm: false}
"""


# ------------------------------------------------------------- shipped config


@pytest.mark.parametrize("profile", ["laptop", "vm", "test"])
def test_every_shipped_profile_loads(repo_config_dir: Path, profile: str) -> None:
    settings = load_settings(profile=profile, config_dir=repo_config_dir)
    assert settings.profile == profile
    assert settings.instance_name == profile


def test_test_profile_never_uses_cloud(repo_config_dir: Path) -> None:
    settings = load_settings(profile="test", config_dir=repo_config_dir)
    assert settings.features.private_mode
    assert not settings.features.cloud_llm


# ------------------------------------------------------------- layering


def test_profile_overrides_base_and_keeps_sibling_keys(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": "log: {format: console}\n"})
    settings = load_settings(profile="dev", config_dir=root)
    assert settings.log.format is LogFormat.CONSOLE
    assert settings.log.level is LogLevel.INFO


def test_env_var_overrides_profile(
    make_config_dir: MakeConfigDir, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_config_dir(BASE, {"dev": "log: {level: WARNING}\n"})
    monkeypatch.setenv("INU_LOG__LEVEL", "DEBUG")
    assert load_settings(profile="dev", config_dir=root).log.level is LogLevel.DEBUG


def test_dotenv_overrides_profile_but_env_wins(
    make_config_dir: MakeConfigDir, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_config_dir(BASE, {"dev": ""})
    (tmp_path / ".env").write_text("INU_INSTANCE_NAME=from-dotenv\n", encoding="utf-8")
    assert load_settings(profile="dev", config_dir=root).instance_name == "from-dotenv"

    monkeypatch.setenv("INU_INSTANCE_NAME", "from-env")
    assert load_settings(profile="dev", config_dir=root).instance_name == "from-env"


def test_profile_and_config_dir_come_from_environment(
    make_config_dir: MakeConfigDir, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_config_dir(BASE, {"dev": ""})
    monkeypatch.setenv("INU_PROFILE", "dev")
    monkeypatch.setenv("INU_CONFIG_DIR", str(root))
    assert load_settings().profile == "dev"


def test_secrets_dir_supplies_values(
    make_config_dir: MakeConfigDir, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_config_dir(BASE, {"dev": ""})
    secrets = tmp_path / "run-secrets"
    secrets.mkdir()
    (secrets / "inu_instance_name").write_text("from-secrets-dir", encoding="utf-8")
    monkeypatch.setenv("INU_SECRETS_DIR", str(secrets))
    assert load_settings(profile="dev", config_dir=root).instance_name == "from-secrets-dir"


def test_deep_merge_replaces_lists_and_does_not_mutate_inputs() -> None:
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    override = {"a": {"y": [3]}}
    assert deep_merge(base, override) == {"a": {"x": 1, "y": [3]}, "b": 1}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 1}


# ------------------------------------------------------------- failures


def test_missing_profile_variable_lists_available_profiles(
    make_config_dir: MakeConfigDir,
) -> None:
    root = make_config_dir(BASE, {"alpha": "", "beta": ""})
    with pytest.raises(ConfigError, match=r"INU_PROFILE is not set.*alpha, beta"):
        load_settings(config_dir=root)


def test_unknown_profile_lists_available_profiles(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"alpha": ""})
    with pytest.raises(ConfigError, match=r"Unknown profile 'nope'.*alpha"):
        load_settings(profile="nope", config_dir=root)


def test_no_profiles_at_all(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="none found"):
        load_settings(config_dir=tmp_path / "missing")


def test_missing_base_file(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": ""})
    (root / "base.yaml").unlink()
    with pytest.raises(ConfigError, match="Config file not found"):
        load_settings(profile="dev", config_dir=root)


def test_typo_in_yaml_key_is_rejected(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": "log: {levle: DEBUG}\n"})
    with pytest.raises(ConfigError, match=r"log\.levle: Extra inputs are not permitted"):
        load_settings(profile="dev", config_dir=root)


def test_invalid_enum_value_is_rejected(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": "log: {level: LOUD}\n"})
    with pytest.raises(ConfigError, match=r"log\.level"):
        load_settings(profile="dev", config_dir=root)


def test_missing_required_value_is_rejected(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir("log: {level: INFO, format: json}\n", {"dev": ""})
    with pytest.raises(ConfigError, match=r"features: Field required"):
        load_settings(profile="dev", config_dir=root)


def test_malformed_yaml_names_the_file(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": "log: [unclosed\n"})
    with pytest.raises(ConfigError, match=r"Invalid YAML in .*dev\.yaml"):
        load_settings(profile="dev", config_dir=root)


def test_yaml_root_must_be_a_mapping(make_config_dir: MakeConfigDir) -> None:
    root = make_config_dir(BASE, {"dev": "- just\n- a list\n"})
    with pytest.raises(ConfigError, match="mapping at the top level"):
        load_settings(profile="dev", config_dir=root)


def test_error_message_never_echoes_secret_values(
    make_config_dir: MakeConfigDir, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_config_dir(BASE, {"dev": "log: {level: LOUD}\n"})
    monkeypatch.setenv("INU_SECRETS__GROQ_API_KEY", "gsk_super_secret")
    with pytest.raises(ConfigError) as caught:
        load_settings(profile="dev", config_dir=root)
    assert "gsk_super_secret" not in str(caught.value)
