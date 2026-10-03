import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from inu_lab import datasets as ds
from inu_lab import stt
from inu_lab.datasets import DatasetSpec, Utterance, load_manifest, prepare

REPO_BENCHMARKS = Path(__file__).resolve().parents[3] / "benchmarks"


def wav_bytes(seconds: float, rate: int = 16_000, fmt: str = "WAV") -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(int(seconds * rate), dtype=np.float32), rate, format=fmt)
    return buffer.getvalue()


def spec(**overrides: object) -> DatasetSpec:
    base: dict[str, object] = {
        "kind": "librispeech",
        "source": "https://example.invalid/test-clean.tar.gz",
        "utterances": 2,
        "seed": 1,
        "min_seconds": 1.0,
        "max_seconds": 5.0,
    }
    base.update(overrides)
    return DatasetSpec.model_validate(base)


class EchoEngine:
    """Returns scripted transcripts in order."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)

    def transcribe(self, samples: np.ndarray) -> str:
        return next(self._answers)


# ------------------------------------------------------------------ config


def test_shipped_stt_config_is_valid() -> None:
    config = stt.SttBenchConfig.load(REPO_BENCHMARKS / "stt.yaml")
    names = [engine.name for engine in config.engines]
    assert len(names) == len(set(names))
    assert {"librispeech-clean", "svarah"} <= set(config.datasets)


def test_build_engine_fills_in_the_shared_thread_count(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[stt.SttEngineSpec] = []

    def record(engine_spec: stt.SttEngineSpec) -> EchoEngine:
        seen.append(engine_spec)
        return EchoEngine([])

    monkeypatch.setitem(stt.ENGINE_KINDS, "moonshine", record)
    engine_spec = stt.SttEngineSpec(name="m", kind="moonshine", model="tiny")
    stt.build_engine(engine_spec, cpu_threads=6)
    assert seen[0].threads == 6


# ------------------------------------------------------------------ scoring


def test_wer_ignores_case_punctuation_and_spelling_variants() -> None:
    assert stt.word_error_rate(["HELLO WORLD"], ["Hello, world!"]) == 0.0
    assert stt.word_error_rate(["the colour grey"], ["the color gray"]) == 0.0
    # Not number words: the normalizer turns "one two three" into a single numeral.
    assert stt.word_error_rate(["the quick brown fox"], ["the quick brown"]) == pytest.approx(0.25)
    assert stt.word_error_rate(["twenty five"], ["25"]) == 0.0


def test_bench_engine_reports_accuracy_latency_and_worst_cases(tmp_path: Path) -> None:
    utterances = []
    for index, seconds in enumerate([2.0, 8.0]):
        path = tmp_path / f"u{index}.wav"
        path.write_bytes(wav_bytes(seconds))
        utterances.append(Utterance(path, f"reference number {index}", seconds))
    ticks = iter([0.0, 0.1, 1.0, 1.4])  # 100 ms and 400 ms transcriptions

    report = stt.bench_engine(
        EchoEngine(["reference number 0", "something else"]),
        "fake",
        "set",
        utterances,
        load_s=1.5,
        warmup=0,
        short_seconds=5.0,
        clock=lambda: next(ticks),
    )

    assert report.wer == pytest.approx(3 / 6)
    assert report.short_latency_p50_ms == pytest.approx(100)
    assert report.latency_p95_ms == pytest.approx(385)
    assert report.rtf == pytest.approx(0.5 / 10)
    assert report.worst[0]["hyp"] == "something else"
    assert stt.table_row(report)[0] == "fake"


# ------------------------------------------------------------------ datasets


def test_subset_is_seeded_filtered_and_resampled(tmp_path: Path) -> None:
    candidates = [
        ("too-short", "a", wav_bytes(0.5)),
        ("ok-1", "first", wav_bytes(2.0, rate=48_000)),
        ("too-long", "c", wav_bytes(9.0)),
        ("ok-2", "second", wav_bytes(3.0)),
        ("blank", "  ", wav_bytes(2.0)),
    ]
    ds._write_subset(candidates, spec(utterances=5), tmp_path)

    utterances = load_manifest(tmp_path)
    assert sorted(u.text for u in utterances) == ["first", "second"]
    for utterance in utterances:
        assert len(utterance.load()) == int(utterance.seconds * 16_000)


def test_wrong_rate_wav_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "x.wav"
    path.write_bytes(wav_bytes(1.0, rate=8_000))
    utterance = Utterance(path, "x", 1.0)
    with pytest.raises(ValueError, match="expected 16000"):
        utterance.load()


def test_librispeech_archive_is_read_into_candidates(tmp_path: Path) -> None:
    archive = tmp_path / "_downloads" / "test-clean.tar.gz"
    archive.parent.mkdir()
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in [
            (
                "LibriSpeech/test-clean/1/2/1-2.trans.txt",
                b"1-2-0000 HELLO THERE\n1-2-0001 GOODBYE\n",
            ),
            ("LibriSpeech/test-clean/1/2/1-2-0000.flac", wav_bytes(2.0, fmt="FLAC")),
            ("LibriSpeech/test-clean/1/2/1-2-0001.flac", wav_bytes(3.0, fmt="FLAC")),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    target = prepare("libri", spec(), tmp_path)

    texts = sorted(u.text for u in load_manifest(target))
    assert texts == ["GOODBYE", "HELLO THERE"]
    assert prepare("libri", spec(), tmp_path) == target  # second call reuses the manifest


def test_download_names_the_file_after_the_url_and_reuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fetched: list[tuple[str, Path]] = []

    def fake_fetch(url: str, target: Path, *, timeout_s: float) -> Path:
        fetched.append((url, target))
        target.write_bytes(b"abcdef")
        return target

    monkeypatch.setattr(ds, "fetch", fake_fetch)  # resuming is tested in inu.assets

    path = ds.download("https://example.invalid/data.tar.gz", tmp_path / "dl")

    assert path == tmp_path / "dl" / "data.tar.gz"
    assert ds.download("https://example.invalid/data.tar.gz", tmp_path / "dl") == path
    assert len(fetched) == 1


def test_manifest_round_trip(tmp_path: Path) -> None:
    (tmp_path / ds.MANIFEST).write_text(
        json.dumps({"path": "a.wav", "text": "hi", "seconds": 1.5}) + "\n", "utf-8"
    )
    (utterance,) = load_manifest(tmp_path)
    assert utterance.path == tmp_path / "a.wav"
    assert utterance.seconds == 1.5
