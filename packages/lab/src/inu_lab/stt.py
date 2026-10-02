"""Speech-to-text benchmark.

Every engine transcribes the same prepared utterances (see `datasets.py`). Reported:
word error rate after Whisper-style normalisation, latency per utterance (overall and
for short, command-length utterances, which is what a voice assistant mostly hears),
real-time factor, and load time. Engines are built lazily so a missing optional
dependency only disables that engine.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import jiwer
import yaml
from pydantic import BaseModel, ConfigDict, Field
from whisper_normalizer.english import EnglishTextNormalizer

from inu_lab.datasets import TARGET_RATE, DatasetSpec, Samples, Utterance
from inu_lab.results import percentile

_normalize = EnglishTextNormalizer()


class SttEngineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: Literal["faster_whisper", "onnx_asr", "moonshine"]
    model: str
    device: Literal["cpu", "cuda"] = "cpu"
    threads: int | None = Field(default=None, ge=1, description="Overrides cpu_threads.")
    compute_type: str = "int8"  # faster_whisper
    beam_size: int = Field(default=1, ge=1)  # faster_whisper; greedy is the latency choice
    quantization: str | None = None  # onnx_asr, e.g. "int8"


class SttBenchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path
    cpu_threads: int = Field(ge=1)
    datasets: dict[str, DatasetSpec]
    engines: list[SttEngineSpec] = Field(min_length=1)
    warmup_utterances: int = Field(ge=0)
    short_seconds: float = Field(
        gt=0, description="Utterances up to this length count as commands."
    )

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class SttEngine(Protocol):
    def transcribe(self, samples: Samples) -> str:
        """16 kHz mono float32 in, text out."""
        ...


# ------------------------------------------------------------------ engines


class _FasterWhisper:
    def __init__(self, spec: SttEngineSpec) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            spec.model,
            device=spec.device,
            compute_type=spec.compute_type,
            cpu_threads=spec.threads or 0,
        )
        self._beam = spec.beam_size

    def transcribe(self, samples: Samples) -> str:
        segments, _ = self._model.transcribe(
            samples,
            language="en",
            beam_size=self._beam,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments)


class _OnnxAsr:
    def __init__(self, spec: SttEngineSpec) -> None:
        import onnx_asr
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = spec.threads or 0
        provider = "CUDAExecutionProvider" if spec.device == "cuda" else "CPUExecutionProvider"
        self._model = onnx_asr.load_model(
            spec.model, quantization=spec.quantization, sess_options=options, providers=[provider]
        )

    def transcribe(self, samples: Samples) -> str:
        return str(self._model.recognize(samples, sample_rate=TARGET_RATE))


class _Moonshine:
    def __init__(self, spec: SttEngineSpec) -> None:
        import moonshine_voice as mv

        path, arch = mv.get_model_for_language("en", mv.ModelArch[spec.model.upper()])
        self._transcriber = mv.transcriber.Transcriber(path, arch)

    def transcribe(self, samples: Samples) -> str:
        transcript = self._transcriber.transcribe_without_streaming(samples.tolist(), TARGET_RATE)
        return " ".join(line.text.strip() for line in transcript.lines)


ENGINE_KINDS: dict[str, Callable[[SttEngineSpec], SttEngine]] = {
    "faster_whisper": _FasterWhisper,
    "onnx_asr": _OnnxAsr,
    "moonshine": _Moonshine,
}


def build_engine(spec: SttEngineSpec, cpu_threads: int) -> SttEngine:
    if spec.threads is None:
        spec = spec.model_copy(update={"threads": cpu_threads})
    return ENGINE_KINDS[spec.kind](spec)


# ------------------------------------------------------------------ measurement


@dataclass
class SttReport:
    engine: str
    dataset: str
    utterances: int
    audio_seconds: float
    load_s: float
    wer: float
    latency_p50_ms: float
    latency_p95_ms: float
    short_latency_p50_ms: float
    short_latency_p95_ms: float
    rtf: float  # compute time / audio time; below 1 is faster than real time
    worst: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def word_error_rate(references: list[str], hypotheses: list[str]) -> float:
    refs = [_normalize(text) for text in references]
    hyps = [_normalize(text) for text in hypotheses]
    pairs = [(r, h) for r, h in zip(refs, hyps, strict=True) if r.strip()]
    return float(jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]))


def bench_engine(
    engine: SttEngine,
    name: str,
    dataset: str,
    utterances: list[Utterance],
    *,
    load_s: float,
    warmup: int,
    short_seconds: float,
    clock: Callable[[], float] = time.perf_counter,
) -> SttReport:
    audio = [u.load() for u in utterances]
    for samples in audio[:warmup]:
        engine.transcribe(samples)

    hypotheses: list[str] = []
    latencies_ms: list[float] = []
    for samples in audio:
        started = clock()
        hypotheses.append(engine.transcribe(samples))
        latencies_ms.append((clock() - started) * 1000)

    references = [u.text for u in utterances]
    short = [
        ms for ms, u in zip(latencies_ms, utterances, strict=True) if u.seconds <= short_seconds
    ]
    audio_seconds = sum(u.seconds for u in utterances)
    per_utterance = [
        (word_error_rate([ref], [hyp]) if _normalize(ref).strip() else 0.0, ref, hyp)
        for ref, hyp in zip(references, hypotheses, strict=True)
    ]
    worst = sorted(per_utterance, key=lambda item: item[0], reverse=True)[:3]
    return SttReport(
        engine=name,
        dataset=dataset,
        utterances=len(utterances),
        audio_seconds=audio_seconds,
        load_s=load_s,
        wer=word_error_rate(references, hypotheses),
        latency_p50_ms=percentile(latencies_ms, 50),
        latency_p95_ms=percentile(latencies_ms, 95),
        short_latency_p50_ms=percentile(short, 50),
        short_latency_p95_ms=percentile(short, 95),
        rtf=sum(latencies_ms) / 1000 / audio_seconds if audio_seconds else float("nan"),
        worst=[{"wer": f"{w:.2f}", "ref": r, "hyp": h} for w, r, h in worst],
    )


TABLE_HEADERS = (
    "engine",
    "dataset",
    "WER %",
    "short p50 ms",
    "short p95 ms",
    "all p50 ms",
    "RTF",
    "load s",
)


def table_row(report: SttReport) -> tuple[object, ...]:
    return (
        report.engine,
        report.dataset,
        report.wer * 100,
        report.short_latency_p50_ms,
        report.short_latency_p95_ms,
        report.latency_p50_ms,
        report.rtf,
        report.load_s,
    )
