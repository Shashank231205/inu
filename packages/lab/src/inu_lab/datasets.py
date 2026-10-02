"""Speech test sets: download once, sample a fixed subset, write a manifest.

Every STT model is scored on exactly the same utterances: a seeded random sample
within a duration range, recorded in `manifest.jsonl` (audio path, reference text,
duration). Audio is stored as 16 kHz mono WAV so engines never resample differently.
"""

import io
import json
import random
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import httpx
import numpy as np
import numpy.typing as npt
import soundfile as sf
import soxr
from pydantic import BaseModel, ConfigDict, Field

TARGET_RATE: Final = 16_000

type Samples = npt.NDArray[np.float32]
MANIFEST = "manifest.jsonl"


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["librispeech", "hf_parquet"]
    source: str = Field(description="URL for librispeech, repo id for hf_parquet")
    utterances: int = Field(gt=0)
    seed: int
    min_seconds: float = Field(gt=0)
    max_seconds: float = Field(gt=0)
    audio_column: str = "audio"
    text_column: str = "text"


@dataclass(frozen=True)
class Utterance:
    path: Path
    text: str
    seconds: float

    def load(self) -> Samples:
        samples, rate = sf.read(self.path, dtype="float32")
        if rate != TARGET_RATE:
            raise ValueError(f"{self.path} is {rate} Hz, expected {TARGET_RATE}")
        return np.asarray(samples, dtype=np.float32)


def load_manifest(directory: Path) -> list[Utterance]:
    lines = (directory / MANIFEST).read_text("utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    return [Utterance(directory / row["path"], row["text"], row["seconds"]) for row in rows]


def prepare(name: str, spec: DatasetSpec, root: Path) -> Path:
    """Build the subset if it isn't there yet. Returns its directory."""
    target = root / name
    if (target / MANIFEST).is_file():
        return target
    target.mkdir(parents=True, exist_ok=True)
    if spec.kind == "librispeech":
        candidates = _librispeech_candidates(spec, root / "_downloads")
    else:
        candidates = _hf_parquet_candidates(spec)
    _write_subset(candidates, spec, target)
    return target


# ------------------------------------------------------------------ sources

type Candidate = tuple[str, str, bytes]  # id, reference text, encoded audio


def _librispeech_candidates(spec: DatasetSpec, downloads: Path) -> list[Candidate]:
    archive = download(spec.source, downloads)
    transcripts: dict[str, str] = {}
    audio: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            data = tar.extractfile(member)
            if data is None:
                continue
            if member.name.endswith(".trans.txt"):
                for line in data.read().decode("utf-8").splitlines():
                    utt_id, _, text = line.partition(" ")
                    transcripts[utt_id] = text
            elif member.name.endswith(".flac"):
                audio[Path(member.name).stem] = data.read()
    return [(uid, transcripts[uid], audio[uid]) for uid in sorted(audio) if uid in transcripts]


def _hf_parquet_candidates(spec: DatasetSpec) -> list[Candidate]:
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    files = sorted(
        f
        for f in HfApi().list_repo_files(spec.source, repo_type="dataset")
        if f.endswith(".parquet")
    )
    candidates: list[Candidate] = []
    for file in files:
        table = pq.read_table(hf_hub_download(spec.source, file, repo_type="dataset"))
        for index, row in enumerate(
            table.select([spec.audio_column, spec.text_column]).to_pylist()
        ):
            candidates.append(
                (
                    f"{Path(file).stem}-{index}",
                    row[spec.text_column],
                    row[spec.audio_column]["bytes"],
                )
            )
    return candidates


def download(url: str, directory: Path) -> Path:
    """Fetch `url` into `directory` once; later calls reuse the file."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / url.rsplit("/", 1)[-1]
    if path.is_file():
        return path
    partial = path.with_suffix(path.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as out:
            for chunk in response.iter_bytes(1 << 20):
                out.write(chunk)
    partial.replace(path)
    return path


# ------------------------------------------------------------------ subset


def _write_subset(candidates: list[Candidate], spec: DatasetSpec, target: Path) -> None:
    rng = random.Random(spec.seed)  # noqa: S311 - reproducible sampling, not security
    rng.shuffle(candidates)
    rows = []
    for utt_id, text, encoded in candidates:
        samples, rate = sf.read(io.BytesIO(encoded), dtype="float32", always_2d=True)
        mono = samples.mean(axis=1)
        seconds = len(mono) / rate
        if not spec.min_seconds <= seconds <= spec.max_seconds or not text.strip():
            continue
        if rate != TARGET_RATE:
            mono = soxr.resample(mono, rate, TARGET_RATE, quality="HQ")
        path = f"{utt_id}.wav"
        sf.write(target / path, mono, TARGET_RATE, subtype="PCM_16")
        rows.append({"path": path, "text": text.strip(), "seconds": round(seconds, 3)})
        if len(rows) == spec.utterances:
            break
    (target / MANIFEST).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
