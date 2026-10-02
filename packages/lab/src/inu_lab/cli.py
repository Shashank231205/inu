"""`inu bench`: benchmark candidate models on this machine. Registered as a CLI plugin."""

import argparse
import gc
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from inu.config import Settings
from inu_lab import llm, stt, tts
from inu_lab.datasets import load_manifest, prepare
from inu_lab.machine import describe_machine
from inu_lab.results import markdown_table, save_results

DEFAULT_OUT = Path("benchmarks/results")


def make_llm_backend(config: llm.LlmBenchConfig) -> llm.ChatBackend:
    return llm.OllamaBackend(config.base_url, config.request_timeout_s)


def use_system_trust_store() -> None:
    """Model and dataset downloads go through HTTPS that may be intercepted locally."""
    import truststore

    truststore.inject_into_ssl()


class BenchCommand:
    name = "bench"
    help = "Benchmark candidate models on this machine"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        kinds = parser.add_subparsers(dest="bench_kind", required=True)

        llm_parser = kinds.add_parser("llm", help="Local LLMs through Ollama")
        llm_parser.add_argument("--config", type=Path, default=Path("benchmarks/llm.yaml"))
        llm_parser.add_argument("--models", help="Comma-separated subset of the configured models")
        llm_parser.add_argument(
            "--option",
            action="append",
            default=[],
            metavar="KEY=VALUE",
            help="Override an Ollama option for this run, e.g. num_gpu=99 (repeatable)",
        )
        llm_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)

        stt_parser = kinds.add_parser("stt", help="Speech-to-text engines on prepared test sets")
        stt_parser.add_argument("--config", type=Path, default=Path("benchmarks/stt.yaml"))
        stt_parser.add_argument("--engines", help="Comma-separated subset of engine names")
        stt_parser.add_argument("--datasets", help="Comma-separated subset of dataset names")
        stt_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)

        tts_parser = kinds.add_parser(
            "tts", help="Text-to-speech engines; saves audio to listen to"
        )
        tts_parser.add_argument("--config", type=Path, default=Path("benchmarks/tts.yaml"))
        tts_parser.add_argument("--engines", help="Comma-separated subset of engine names")
        tts_parser.add_argument("--out", type=Path, default=DEFAULT_OUT)

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
        if args.bench_kind == "llm":
            return run_llm(args.config, args.models, args.out, args.option)
        if args.bench_kind == "stt":
            return run_stt(args.config, args.engines, args.datasets, args.out)
        return run_tts(args.config, args.engines, args.out)


def _subset(available: list[str], wanted: str | None, what: str) -> list[str] | None:
    if not wanted:
        return available
    chosen = [item.strip() for item in wanted.split(",") if item.strip()]
    unknown = sorted(set(chosen) - set(available))
    if unknown:
        print(f"unknown {what}: {', '.join(unknown)}", file=sys.stderr)
        return None
    return chosen


# ------------------------------------------------------------------ llm


def parse_options(pairs: list[str]) -> dict[str, Any]:
    """`key=value` strings; values are parsed as YAML scalars (99 -> int, true -> bool)."""
    options: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        options[key.strip()] = yaml.safe_load(value)
    return options


def run_llm(
    config_path: Path, models_arg: str | None, out_dir: Path, option_pairs: list[str] | None = None
) -> int:
    config = llm.LlmBenchConfig.load(config_path)
    try:
        overrides = parse_options(option_pairs or [])
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if overrides:
        config = config.model_copy(update={"options": {**config.options, **overrides}})
    models = _subset(config.models, models_arg, f"models (not in {config_path})")
    if models is None:
        return 2

    backend = make_llm_backend(config)
    reports: list[dict[str, Any]] = []
    rows = []
    for index, model in enumerate(models, start=1):
        print(f"[{index}/{len(models)}] {model}", file=sys.stderr, flush=True)
        try:
            report = llm.bench_model(backend, config, model)
        except httpx.HTTPError as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            reports.append({"model": model, "error": str(exc)})
            continue
        reports.append(report.to_dict())
        rows.append(llm.table_row(report))

    path = save_results(
        "llm",
        {"machine": describe_machine(), "config": config.model_dump(), "models": reports},
        out_dir,
    )
    print(markdown_table(llm.TABLE_HEADERS, rows))
    print(f"\nraw results: {path}")
    return 0 if rows else 1


# ------------------------------------------------------------------ stt


def run_stt(
    config_path: Path, engines_arg: str | None, datasets_arg: str | None, out_dir: Path
) -> int:
    config = stt.SttBenchConfig.load(config_path)
    engine_names = _subset([e.name for e in config.engines], engines_arg, "engines")
    dataset_names = _subset(list(config.datasets), datasets_arg, "datasets")
    if engine_names is None or dataset_names is None:
        return 2
    use_system_trust_store()

    prepared: dict[str, list[Any]] = {}
    for name in dataset_names:
        print(f"preparing dataset {name}", file=sys.stderr, flush=True)
        try:
            prepared[name] = load_manifest(prepare(name, config.datasets[name], config.data_dir))
        except Exception as exc:  # noqa: BLE001 - a gated or offline dataset must not stop the run
            print(f"  skipped: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)

    reports: list[dict[str, Any]] = []
    rows = []
    specs = [e for e in config.engines if e.name in engine_names]
    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] {spec.name}", file=sys.stderr, flush=True)
        try:
            started = time.perf_counter()
            engine = stt.build_engine(spec, config.cpu_threads)
            load_s = time.perf_counter() - started
            for dataset, utterances in prepared.items():
                report = stt.bench_engine(
                    engine,
                    spec.name,
                    dataset,
                    utterances,
                    load_s=load_s,
                    warmup=config.warmup_utterances,
                    short_seconds=config.short_seconds,
                )
                reports.append(report.to_dict())
                rows.append(stt.table_row(report))
                print(f"  {dataset}: WER {report.wer:.1%}", file=sys.stderr, flush=True)
            del engine
            gc.collect()
        except Exception as exc:  # noqa: BLE001 - one broken engine must not stop the bake-off
            print(f"  failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            reports.append({"engine": spec.name, "error": f"{type(exc).__name__}: {exc}"})

    path = save_results(
        "stt",
        {
            "machine": describe_machine(),
            "config": config.model_dump(mode="json"),
            "engines": reports,
        },
        out_dir,
    )
    print(markdown_table(stt.TABLE_HEADERS, rows))
    print(f"\nraw results: {path}")
    return 0 if rows else 1


# ------------------------------------------------------------------ tts


def run_tts(config_path: Path, engines_arg: str | None, out_dir: Path) -> int:
    config = tts.TtsBenchConfig.load(config_path)
    engine_names = _subset([e.name for e in config.engines], engines_arg, "engines")
    if engine_names is None:
        return 2
    use_system_trust_store()

    stt_config = stt.SttBenchConfig.load(config.judge.stt_config)
    judge_spec = next((e for e in stt_config.engines if e.name == config.judge.engine), None)
    if judge_spec is None:
        print(
            f"judge engine {config.judge.engine!r} not in {config.judge.stt_config}",
            file=sys.stderr,
        )
        return 2
    judge = stt.build_engine(judge_spec, stt_config.cpu_threads)

    reports: list[dict[str, Any]] = []
    rows = []
    specs = [e for e in config.engines if e.name in engine_names]
    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] {spec.name}", file=sys.stderr, flush=True)
        try:
            started = time.perf_counter()
            engine = tts.build_engine(spec, config.models_dir)
            load_s = time.perf_counter() - started
            report = tts.bench_engine(
                engine,
                spec,
                config.replies,
                load_s=load_s,
                warmup=config.warmup,
                judge=judge,
                samples_dir=config.samples_dir,
            )
            del engine
            gc.collect()
        except Exception as exc:  # noqa: BLE001 - one broken engine must not stop the bake-off
            print(f"  failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            reports.append({"engine": spec.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        reports.append(report.to_dict())
        rows.append(tts.table_row(report))

    path = save_results(
        "tts",
        {
            "machine": describe_machine(),
            "config": config.model_dump(mode="json"),
            "engines": reports,
        },
        out_dir,
    )
    print(markdown_table(tts.TABLE_HEADERS, rows))
    print(f"\nraw results: {path}\nlisten: {config.samples_dir}")
    return 0 if rows else 1
