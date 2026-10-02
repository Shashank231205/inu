import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from inu import cli
from inu.cli import DIAG_STAGES, EXIT_CONFIG_ERROR, main
from inu.config import Settings
from inu.observability import Telemetry, build_telemetry, configure_logging
from support import OTel


@pytest.fixture(autouse=True)
def config_dir_env(monkeypatch: pytest.MonkeyPatch, repo_config_dir: Path) -> None:
    monkeypatch.setenv("INU_CONFIG_DIR", str(repo_config_dir))


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


def test_diag_emits_one_turn_with_every_stage(
    otel: OTel, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_init(settings: Settings) -> Telemetry:
        # The session already installed global providers; don't replace them.
        configure_logging(settings.log)
        return build_telemetry(settings)

    monkeypatch.setattr(cli, "init_observability", fake_init)

    assert main(["diag", "--profile", "test"]) == 0

    names = [span.name for span in otel.spans.get_finished_spans()]
    assert names == [*(f"stage.{s}" for s in DIAG_STAGES), "turn"]
    assert "Emitted diagnostic turn" in capsys.readouterr().out


def test_profile_works_before_or_after_the_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--profile", "vm", "config", "check"]) == 0
    assert main(["config", "check", "--profile", "vm"]) == 0
    assert capsys.readouterr().out.count("profile: vm") == 2


class _FakeEntryPoint:
    def __init__(self, name: str, factory: object) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> object:
        if isinstance(self._factory, Exception):
            raise self._factory
        return self._factory


def test_plugins_are_discovered_and_bad_ones_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Extra:
        name = "extra"
        help = "An extra command"

    monkeypatch.setattr(
        cli,
        "entry_points",
        lambda group: [
            _FakeEntryPoint("extra", Extra),
            _FakeEntryPoint("broken", ImportError("no module named nope")),
            _FakeEntryPoint("dup", cli.ConfigCommand),
        ],
    )

    names = [command.name for command in cli.discover_commands()]

    assert names == ["config", "diag", "extra"]
    err = capsys.readouterr().err
    assert "skipping command plugin 'broken': no module named nope" in err
    assert "duplicate command 'config' ignored" in err


def test_installed_voice_package_contributes_audio_command() -> None:
    assert "audio" in [command.name for command in cli.discover_commands()]


def test_diag_end_to_end_in_a_fresh_process(repo_config_dir: Path) -> None:
    """Real entry point, real global providers, console exporters."""
    env = {
        **os.environ,
        "INU_CONFIG_DIR": str(repo_config_dir),
        "INU_TELEMETRY__TRACES__EXPORTER": "console",
        "INU_LOG__FORMAT": "json",
        "INU_LOG__LEVEL": "INFO",
    }
    result = subprocess.run(
        [sys.executable, "-m", "inu.cli", "diag", "--profile", "test"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=True,
    )
    turn_id = result.stdout.strip().splitlines()[-1].removeprefix("Emitted diagnostic turn ")
    for name in DIAG_STAGES:
        assert f'"name": "stage.{name}"' in result.stdout
    logs = [json.loads(line) for line in result.stderr.splitlines()]
    assert [entry["stage"] for entry in logs] == list(DIAG_STAGES)
    assert {entry["turn_id"] for entry in logs} == {turn_id}
    assert all(len(entry["trace_id"]) == 32 for entry in logs)
