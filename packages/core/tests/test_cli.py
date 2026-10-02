import os
from pathlib import Path

import pytest

from inu.cli import EXIT_CONFIG_ERROR, main

REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INU_CONFIG_DIR", str(REPO_CONFIG_DIR))


def test_check_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "check", "--profile", "laptop"]) == 0
    assert "Configuration OK (profile: laptop)" in capsys.readouterr().out


def test_show_prints_yaml_with_secrets_redacted(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INU_SECRETS__GROQ_API_KEY", "gsk_super_secret")
    assert main(["config", "show", "--profile", "laptop"]) == 0
    out = capsys.readouterr().out
    assert "instance_name: laptop" in out
    assert "gsk_super_secret" not in out
    assert "groq_api_key: '**********'" in out


def test_bad_config_exits_with_config_error_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "check", "--profile", "nope"]) == EXIT_CONFIG_ERROR
    assert "Unknown profile 'nope'" in capsys.readouterr().err
