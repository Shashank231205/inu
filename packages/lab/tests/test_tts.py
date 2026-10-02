from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from inu_lab import tts

REPO_BENCHMARKS = Path(__file__).resolve().parents[3] / "benchmarks"


class ToneEngine:
    """One second of audio per call, at a 24 kHz rate like Kokoro."""

    def __init__(self) -> None:
        self.sentences: list[str] = []

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        self.sentences.append(text)
        return np.zeros(24_000, dtype=np.float32), 24_000


class ParrotJudge:
    """Hears exactly what each reply said, except it drops the word 'Pune'."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = iter(replies)
        self.rates: list[int] = []

    def transcribe(self, samples: np.ndarray) -> str:
        self.rates.append(len(samples))
        return next(self._replies).replace("Pune", "")


def test_shipped_tts_config_is_valid() -> None:
    config = tts.TtsBenchConfig.load(REPO_BENCHMARKS / "tts.yaml")
    assert len({e.name for e in config.engines}) == len(config.engines)
    assert config.judge.stt_config.name == "stt.yaml"


@pytest.mark.parametrize(
    ("text", "sentences"),
    [
        ("Yes?", ["Yes?"]),
        ("Done. I've opened Spotify.", ["Done.", "I've opened Spotify."]),
        ("It's 3.5 degrees.", ["It's 3.5 degrees."]),
    ],
)
def test_split_sentences(text: str, sentences: list[str]) -> None:
    assert tts.split_sentences(text) == sentences


def test_bench_engine_times_first_sentence_saves_audio_and_scores(tmp_path: Path) -> None:
    replies = ["Done. It's sunny in Pune.", "Yes?"]
    spec = tts.TtsEngineSpec(name="tone", kind="moonshine", voice="v", language="en-gb")
    engine = ToneEngine()
    judge = ParrotJudge(replies)
    ticks = iter([0.0, 0.1, 0.1, 0.3, 0.3, 0.35])  # sentence times: 100, 200, 50 ms

    report = tts.bench_engine(
        engine,
        spec,
        replies,
        load_s=2.0,
        warmup=0,
        judge=judge,
        samples_dir=tmp_path,
        clock=lambda: next(ticks),
    )

    assert engine.sentences == ["Done.", "It's sunny in Pune.", "Yes?"]
    assert report.first_audio_p50_ms == pytest.approx(75)
    assert report.first_audio_max_ms == pytest.approx(100)
    assert report.rtf == pytest.approx(0.35 / 3)
    # "done it is sunny in pune" + "yes": 7 normalised words, one dropped
    assert report.intelligibility_wer == pytest.approx(1 / 7)
    assert judge.rates == [32_000, 16_000]  # resampled to 16 kHz for the judge
    saved = sorted((tmp_path / "tone").glob("*.wav"))
    assert [sf.info(p).duration for p in saved] == [2.0, 1.0]
    assert tts.table_row(report)[0] == "tone"


def test_build_engine_dispatches_on_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    built: list[tuple[str, Path]] = []

    def fake(spec: tts.TtsEngineSpec, models_dir: Path) -> ToneEngine:
        built.append((spec.name, models_dir))
        return ToneEngine()

    monkeypatch.setitem(tts.ENGINE_KINDS, "piper", fake)
    spec = tts.TtsEngineSpec(name="p", kind="piper", voice="v", language="en-gb")
    tts.build_engine(spec, tmp_path)
    assert built == [("p", tmp_path)]
