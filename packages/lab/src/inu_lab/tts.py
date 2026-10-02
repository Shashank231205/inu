"""Text-to-speech benchmark.

Every engine speaks the same replies, one sentence at a time (the way INU's streaming
TTS will feed the speaker), so "first audio" is the time to synthesize the first
sentence. Also reported: real-time factor, and intelligibility as the word error rate
when a reference STT engine transcribes the output. Every engine's audio is saved as
WAV so voices can be compared by ear.
"""

import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import numpy as np
import soundfile as sf
import soxr
import yaml
from pydantic import BaseModel, ConfigDict, Field

from inu_lab.datasets import TARGET_RATE, download
from inu_lab.results import percentile
from inu_lab.stt import SttEngine, word_error_rate

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class TtsEngineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: Literal["kokoro_onnx", "piper", "moonshine"]
    voice: str
    language: str
    urls: list[str] = Field(default_factory=list, description="Assets to download (kokoro_onnx)")
    hf_repo: str | None = None  # piper voices live on Hugging Face
    hf_files: list[str] = Field(default_factory=list)


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stt_config: Path
    engine: str


class TtsBenchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    models_dir: Path
    samples_dir: Path
    replies: list[str] = Field(min_length=1)
    warmup: int = Field(ge=0)
    judge: JudgeSpec
    engines: list[TtsEngineSpec] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class TtsEngine(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Text in, mono float32 samples and their sample rate out."""
        ...


def split_sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(text.strip()) if part]


# ------------------------------------------------------------------ engines


class _KokoroOnnx:
    def __init__(self, spec: TtsEngineSpec, models_dir: Path) -> None:
        from kokoro_onnx import Kokoro

        model, voices = (download(url, models_dir / "kokoro") for url in spec.urls)
        self._kokoro = Kokoro(str(model), str(voices))
        self._voice, self._lang = spec.voice, spec.language

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        samples, rate = self._kokoro.create(text, voice=self._voice, lang=self._lang)
        return np.asarray(samples, dtype=np.float32), int(rate)


class _Piper:
    def __init__(self, spec: TtsEngineSpec, models_dir: Path) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice

        if spec.hf_repo is None:
            raise ValueError(f"{spec.name}: piper engines need hf_repo and hf_files")
        paths = [
            Path(hf_hub_download(spec.hf_repo, file, local_dir=models_dir / "piper"))
            for file in spec.hf_files
        ]
        model = next(p for p in paths if p.suffix == ".onnx")
        self._voice = PiperVoice.load(model)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        chunks = list(self._voice.synthesize(text))
        audio = np.concatenate([chunk.audio_float_array for chunk in chunks])
        return audio.astype(np.float32), chunks[0].sample_rate


class _Moonshine:
    def __init__(self, spec: TtsEngineSpec, models_dir: Path) -> None:
        from moonshine_voice.tts import TextToSpeech

        self._tts = TextToSpeech().language(spec.language).voice(spec.voice).load()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        samples, rate = self._tts.synthesize(text)
        return np.asarray(samples, dtype=np.float32), int(rate)


ENGINE_KINDS: dict[str, Callable[[TtsEngineSpec, Path], TtsEngine]] = {
    "kokoro_onnx": _KokoroOnnx,
    "piper": _Piper,
    "moonshine": _Moonshine,
}


def build_engine(spec: TtsEngineSpec, models_dir: Path) -> TtsEngine:
    return ENGINE_KINDS[spec.kind](spec, models_dir)


# ------------------------------------------------------------------ measurement


@dataclass
class TtsReport:
    engine: str
    voice: str
    sample_rate: int
    load_s: float
    first_audio_p50_ms: float
    first_audio_max_ms: float
    rtf: float
    intelligibility_wer: float
    samples: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bench_engine(
    engine: TtsEngine,
    spec: TtsEngineSpec,
    replies: list[str],
    *,
    load_s: float,
    warmup: int,
    judge: SttEngine,
    samples_dir: Path,
    clock: Callable[[], float] = time.perf_counter,
) -> TtsReport:
    for reply in replies[:warmup]:
        engine.synthesize(reply)

    out_dir = samples_dir / spec.name
    out_dir.mkdir(parents=True, exist_ok=True)
    first_ms: list[float] = []
    compute_s = audio_s = 0.0
    rate = 0
    hypotheses: list[str] = []
    for index, reply in enumerate(replies):
        pieces: list[np.ndarray] = []
        for position, sentence in enumerate(split_sentences(reply)):
            started = clock()
            samples, rate = engine.synthesize(sentence)
            elapsed = clock() - started
            if position == 0:
                first_ms.append(elapsed * 1000)
            compute_s += elapsed
            pieces.append(samples)
        audio = np.concatenate(pieces)
        audio_s += len(audio) / rate
        sf.write(out_dir / f"{index:02d}.wav", audio, rate)
        hypotheses.append(judge.transcribe(_to_judge_rate(audio, rate)))

    return TtsReport(
        engine=spec.name,
        voice=spec.voice,
        sample_rate=rate,
        load_s=load_s,
        first_audio_p50_ms=percentile(first_ms, 50),
        first_audio_max_ms=max(first_ms),
        rtf=compute_s / audio_s if audio_s else float("nan"),
        intelligibility_wer=word_error_rate(replies, hypotheses),
        samples=str(out_dir),
    )


def _to_judge_rate(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == TARGET_RATE:
        return audio
    return np.asarray(soxr.resample(audio, rate, TARGET_RATE, quality="HQ"), dtype=np.float32)


TABLE_HEADERS = (
    "engine",
    "voice",
    "rate Hz",
    "first audio p50 ms",
    "first audio max ms",
    "RTF",
    "round-trip WER %",
    "load s",
)


def table_row(report: TtsReport) -> tuple[object, ...]:
    return (
        report.engine,
        report.voice,
        report.sample_rate,
        report.first_audio_p50_ms,
        report.first_audio_max_ms,
        report.rtf,
        report.intelligibility_wer * 100,
        report.load_s,
    )
