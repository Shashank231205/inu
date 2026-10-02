import json
import os
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
import yaml

from inu.cli import main
from inu_lab import cli as bench_cli
from inu_lab import stt
from inu_lab.llm import LlmBenchConfig
from lab_fakes import FakeOllama

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("INU_CONFIG_DIR", str(REPO / "config"))
    monkeypatch.chdir(tmp_path)


def run(*extra: str) -> int:
    args = ["--profile", "test", "bench", "llm", "--config", str(REPO / "benchmarks" / "llm.yaml")]
    return main([*args, *extra])


def test_runs_selected_models_and_saves_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bench_cli, "make_llm_backend", lambda config: FakeOllama())

    assert run("--models", "llama3.2:3b", "--out", str(tmp_path / "res")) == 0

    out = capsys.readouterr().out
    assert "| llama3.2:3b |" in out
    (saved,) = (tmp_path / "res").glob("*-llm.json")
    payload = json.loads(saved.read_text("utf-8"))
    assert payload["models"][0]["model"] == "llama3.2:3b"
    assert "machine" in payload


def test_option_overrides_reach_every_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = FakeOllama()
    monkeypatch.setattr(bench_cli, "make_llm_backend", lambda config: backend)

    code = run(
        "--models",
        "llama3.2:3b",
        "--option",
        "num_gpu=99",
        "--option",
        "num_ctx=2048",
        "--out",
        str(tmp_path / "res"),
    )

    assert code == 0
    assert all(c["options"]["num_gpu"] == 99 for c in backend.calls)
    assert all(c["options"]["num_ctx"] == 2048 for c in backend.calls)
    configured = LlmBenchConfig.load(REPO / "benchmarks" / "llm.yaml").options["temperature"]
    assert all(c["options"]["temperature"] == configured for c in backend.calls)  # rest kept


def test_malformed_option_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("--option", "num_gpu") == 2
    assert "expected KEY=VALUE" in capsys.readouterr().err


def test_unknown_model_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("--models", "not-a-model") == 2
    assert "not-a-model" in capsys.readouterr().err


def test_stt_runs_engines_on_prepared_datasets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    (data / "tiny").mkdir(parents=True)
    sf.write(data / "tiny" / "a.wav", np.zeros(32_000, dtype=np.float32), 16_000)
    (data / "tiny" / "manifest.jsonl").write_text(
        json.dumps({"path": "a.wav", "text": "hello", "seconds": 2.0}) + "\n", "utf-8"
    )
    dataset = {
        "kind": "librispeech",
        "utterances": 1,
        "seed": 1,
        "min_seconds": 1,
        "max_seconds": 5,
    }
    config = tmp_path / "stt.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "data_dir": data.as_posix(),
                "cpu_threads": 2,
                "warmup_utterances": 0,
                "short_seconds": 5,
                "datasets": {
                    "tiny": {**dataset, "source": "unused"},
                    "offline": {**dataset, "source": "https://example.invalid/x.tar.gz"},
                },
                "engines": [
                    {"name": "good", "kind": "moonshine", "model": "tiny"},
                    {"name": "broken", "kind": "moonshine", "model": "base"},
                ],
            }
        ),
        "utf-8",
    )

    class Hello:
        def transcribe(self, samples: object) -> str:
            return "hello"

    def build(spec: stt.SttEngineSpec, cpu_threads: int) -> Hello:
        if spec.name == "broken":
            raise RuntimeError("model download failed")
        return Hello()

    def fake_prepare(name: str, spec: object, root: Path) -> Path:
        if name == "offline":
            raise OSError("offline")
        return root / name

    monkeypatch.setattr(bench_cli, "use_system_trust_store", lambda: None)
    monkeypatch.setattr(stt, "build_engine", build)
    monkeypatch.setattr(bench_cli, "prepare", fake_prepare)

    code = main(
        [
            "--profile",
            "test",
            "bench",
            "stt",
            "--config",
            str(config),
            "--out",
            str(tmp_path / "res"),
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "| good | tiny | 0.00 |" in captured.out
    assert "skipped: OSError: offline" in captured.err
    assert "failed: RuntimeError: model download failed" in captured.err
    (saved,) = (tmp_path / "res").glob("*-stt.json")
    errors = [e for e in json.loads(saved.read_text("utf-8"))["engines"] if "error" in e]
    assert errors[0]["engine"] == "broken"


def test_stt_unknown_engine_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--profile",
            "test",
            "bench",
            "stt",
            "--config",
            str(REPO / "benchmarks" / "stt.yaml"),
            "--engines",
            "nope",
        ]
    )
    assert code == 2
    assert "unknown engines: nope" in capsys.readouterr().err


def test_backend_errors_are_recorded_not_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Down(FakeOllama):
        def show(self, model: str) -> dict[str, object]:
            raise httpx.ConnectError("ollama is not running")

    monkeypatch.setattr(bench_cli, "make_llm_backend", lambda config: Down())

    assert run("--models", "llama3.2:3b", "--out", str(tmp_path / "res")) == 1

    assert "ollama is not running" in capsys.readouterr().err
    (saved,) = (tmp_path / "res").glob("*-llm.json")
    assert json.loads(saved.read_text("utf-8"))["models"][0]["error"]
