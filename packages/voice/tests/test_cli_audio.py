from pathlib import Path

import pytest

from inu.cli import main
from inu_voice import cli as audio_cli
from inu_voice.cli import EXIT_DEVICE_ERROR
from voice_fakes import FakeBackend, device


@pytest.fixture(autouse=True)
def fake_hardware(monkeypatch: pytest.MonkeyPatch, repo_config_dir: Path) -> FakeBackend:
    backend = FakeBackend()
    monkeypatch.setattr(audio_cli, "make_backend", lambda: backend)
    monkeypatch.setenv("INU_CONFIG_DIR", str(repo_config_dir))
    return backend


def test_devices_marks_what_the_profile_selects(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--profile", "laptop", "audio", "devices"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any("Microphone Array" in line and "<- input" in line for line in lines)
    assert any("Speakers (Realtek)" in line and "<- output" in line for line in lines)


def test_devices_explains_a_bad_device_setting(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INU_AUDIO__INPUT__DEVICE", "Blue Yeti")
    assert main(["--profile", "laptop", "audio", "devices"]) == 0
    assert "input: No input device matching 'Blue Yeti'" in capsys.readouterr().out


def test_bench_without_audio_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--profile", "laptop", "audio", "bench", "--seconds", "0.05", "--cpu-load", "0"])
    assert code == 1
    assert "result              FAIL" in capsys.readouterr().out


def test_bench_reports_device_errors(
    capsys: pytest.CaptureFixture[str], fake_hardware: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        audio_cli, "make_backend", lambda: FakeBackend([device(0, "Mic", "MME", inputs=1)])
    )
    code = main(["--profile", "laptop", "audio", "bench", "--seconds", "0.05"])
    assert code == EXIT_DEVICE_ERROR
    assert "audio error: Host API 'Windows WASAPI' not found" in capsys.readouterr().out
