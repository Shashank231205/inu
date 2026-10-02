"""LLM benchmark against a local Ollama server.

Every model gets INU's real system prompt (`prompts/inu-system.md`) and realistic,
often multi-turn conversations. Per model it measures cold load, warm
time-to-first-token, decode and prefill speed, and VRAM placement. It also scores what
matters for a voice assistant:

* speakable: no markdown, lists or tables
* length: short when a quick answer fits, long when the user asked for depth
* correct: required facts present, forbidden content absent
* guardrails: the same check, reported separately for safety cases
* tools: right function and arguments, and no tool when none is needed
"""

import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from inu_lab.results import percentile

NS_PER_MS = 1_000_000
MIB = 1024 * 1024

_MARKDOWN = re.compile(r"[*#`|]|^\s*([-•]|\d+[.)])\s", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


# ------------------------------------------------------------------ configuration


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(_Frozen):
    role: Literal["user", "assistant"]
    content: str


class LengthRules(_Frozen):
    short_max_sentences: int = Field(ge=1)
    long_min_words: int = Field(ge=1)


class ConversationCase(_Frozen):
    id: str
    category: Literal["knowledge", "reasoning", "conversation", "long", "persona", "guardrail"]
    history: list[Message] = Field(default_factory=list)
    ask: str
    length: Literal["short", "long"]
    expect: str | None = Field(default=None, description="Regex a good answer must contain.")
    forbid: str | None = Field(default=None, description="Regex a good answer must not contain.")

    def verdict(self, answer: str) -> bool | None:
        """None when the case has nothing to grade."""
        if self.expect is None and self.forbid is None:
            return None
        if self.expect and not re.search(self.expect, answer, re.IGNORECASE):
            return False
        return not (self.forbid and re.search(self.forbid, answer, re.IGNORECASE))


class ToolCase(_Frozen):
    id: str
    history: list[Message] = Field(default_factory=list)
    prompt: str
    tool: str | None = Field(description="None: the model must not call any tool.")
    arguments: dict[str, Any] = Field(default_factory=dict)


class LlmBenchConfig(_Frozen):
    base_url: str
    request_timeout_s: float = Field(gt=0)
    models: list[str] = Field(min_length=1)
    system_prompt_file: Path
    system_prompt: str = Field(default="", description="Filled from system_prompt_file on load.")
    conversations: list[ConversationCase] = Field(min_length=1)
    repeats: int = Field(ge=1)
    think: bool = Field(description="Ask thinking-capable models to think (adds latency).")
    length: LengthRules
    options: dict[str, Any]
    tools: list[dict[str, Any]]
    tool_cases: list[ToolCase]

    @classmethod
    def load(cls, path: Path) -> Self:
        config = cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        prompt_path = config.system_prompt_file
        if not prompt_path.is_absolute():
            prompt_path = path.parent / prompt_path  # relative to the YAML file
        return config.model_copy(
            update={"system_prompt": prompt_path.read_text(encoding="utf-8").strip()}
        )


# ------------------------------------------------------------------ backend


class ChatBackend(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        think: bool | None,
    ) -> Iterator[dict[str, Any]]: ...

    def show(self, model: str) -> dict[str, Any]: ...

    def running(self) -> list[dict[str, Any]]: ...

    def unload(self, model: str) -> None: ...


class OllamaBackend:
    """Ollama's native HTTP API."""

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        think: bool | None,
    ) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": options,
        }
        if tools:
            body["tools"] = tools
        if think is not None:
            body["think"] = think
        with self._http.stream("POST", "/api/chat", json=body) as response:
            if response.is_error:
                response.read()  # Ollama explains failures in the body
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from /api/chat: {response.text[:300]}",
                    request=response.request,
                    response=response,
                )
            for line in response.iter_lines():
                if line:
                    yield json.loads(line)

    def show(self, model: str) -> dict[str, Any]:
        response = self._http.post("/api/show", json={"model": model})
        response.raise_for_status()
        return dict(response.json())

    def running(self) -> list[dict[str, Any]]:
        response = self._http.get("/api/ps")
        response.raise_for_status()
        return list(response.json().get("models", []))

    def unload(self, model: str) -> None:
        self._http.post("/api/generate", json={"model": model, "keep_alive": 0}).raise_for_status()


# ------------------------------------------------------------------ measurement


@dataclass
class Turn:
    ttft_ms: float
    total_ms: float
    text: str
    tool_calls: list[dict[str, Any]]
    load_ms: float
    prompt_tokens: int
    prompt_ms: float
    eval_tokens: int
    eval_ms: float

    @property
    def decode_tps(self) -> float:
        return self.eval_tokens / (self.eval_ms / 1000) if self.eval_ms else float("nan")

    @property
    def prefill_tps(self) -> float:
        return self.prompt_tokens / (self.prompt_ms / 1000) if self.prompt_ms else float("nan")


def run_turn(
    backend: ChatBackend,
    model: str,
    messages: list[dict[str, Any]],
    *,
    options: dict[str, Any],
    tools: list[dict[str, Any]] | None = None,
    think: bool | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Turn:
    started = clock()
    first: float | None = None
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    for chunk in backend.chat(model, messages, options=options, tools=tools, think=think):
        message = chunk.get("message", {})
        content = message.get("content", "")
        new_calls = message.get("tool_calls") or []
        if first is None and (content or new_calls):
            first = clock()
        text.append(content)
        calls.extend(new_calls)
        if chunk.get("done"):
            final = chunk
    finished = clock()
    return Turn(
        ttft_ms=((first or finished) - started) * 1000,
        total_ms=(finished - started) * 1000,
        text="".join(text).strip(),
        tool_calls=calls,
        load_ms=final.get("load_duration", 0) / NS_PER_MS,
        prompt_tokens=final.get("prompt_eval_count", 0),
        prompt_ms=final.get("prompt_eval_duration", 0) / NS_PER_MS,
        eval_tokens=final.get("eval_count", 0),
        eval_ms=final.get("eval_duration", 0) / NS_PER_MS,
    )


# ------------------------------------------------------------------ scoring


def is_speakable(text: str) -> bool:
    """Non-empty and free of markdown a voice can't render."""
    return bool(text) and not _MARKDOWN.search(text)


def sentence_count(text: str) -> int:
    return len(_SENTENCE_END.split(text.strip())) if text.strip() else 0


def length_ok(text: str, length: Literal["short", "long"], rules: LengthRules) -> bool:
    if length == "short":
        return 0 < sentence_count(text) <= rules.short_max_sentences
    return len(text.split()) >= rules.long_min_words


def tool_call_matches(calls: list[dict[str, Any]], case: ToolCase) -> bool:
    if case.tool is None:
        return not calls
    for call in calls:
        function = call.get("function", {})
        if function.get("name") != case.tool:
            continue
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if all(_same(arguments.get(key), value) for key, value in case.arguments.items()):
            return True
    return False


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.strip().lower() == expected.lower()
    return bool(actual == expected)


def canonical_name(model: str) -> str:
    """Ollama reports untagged models as `name:latest`."""
    return model if ":" in model else f"{model}:latest"


def _share(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


# ------------------------------------------------------------------ report


@dataclass
class ModelReport:
    model: str
    family: str
    parameters: str
    quantization: str
    capabilities: list[str]
    options: dict[str, Any]
    cold_load_ms: float
    cold_ttft_ms: float
    ttft_p50_ms: float
    ttft_p95_ms: float
    decode_tps: float
    prefill_tps: float
    prompt_tokens_p50: float
    size_mb: float
    vram_mb: float
    gpu_fraction: float
    speakable_rate: float
    length_ok_rate: float
    correct_rate: float | None
    guardrail_rate: float | None
    tool_accuracy: float | None
    answers: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bench_model(backend: ChatBackend, config: LlmBenchConfig, model: str) -> ModelReport:
    info = backend.show(model)
    capabilities = list(info.get("capabilities", []))
    details = info.get("details", {})
    think = config.think if "thinking" in capabilities else None
    tools = config.tools if "tools" in capabilities else None

    for loaded in backend.running():  # free VRAM so the cold load is honest
        backend.unload(loaded["name"])

    def ask(history: list[Message], prompt: str, with_tools: bool = False) -> Turn:
        messages = [
            {"role": "system", "content": config.system_prompt},
            *(m.model_dump() for m in history),
            {"role": "user", "content": prompt},
        ]
        return run_turn(
            backend,
            model,
            messages,
            options=config.options,
            tools=tools if with_tools else None,
            think=think,
        )

    first_case = config.conversations[0]
    cold = ask(first_case.history, first_case.ask)
    placement = next(
        (
            m
            for m in backend.running()
            if canonical_name(m.get("name", "")) == canonical_name(model)
        ),
        {},
    )
    size, size_vram = placement.get("size", 0), placement.get("size_vram", 0)

    runs = [
        (case, ask(case.history, case.ask))
        for _ in range(config.repeats)
        for case in config.conversations
    ]
    tool_results = [
        tool_call_matches(ask(case.history, case.prompt, with_tools=True).tool_calls, case)
        for case in config.tool_cases
    ]
    backend.unload(model)

    turns = [turn for _, turn in runs]
    graded = [
        (case, verdict) for case, turn in runs if (verdict := case.verdict(turn.text)) is not None
    ]
    answers: dict[str, list[str]] = {}
    for case, turn in runs:
        answers.setdefault(case.id, []).append(turn.text)

    return ModelReport(
        model=model,
        family=str(details.get("family", "")),
        parameters=str(details.get("parameter_size", "")),
        quantization=str(details.get("quantization_level", "")),
        capabilities=capabilities,
        options=dict(config.options),
        cold_load_ms=cold.load_ms,
        cold_ttft_ms=cold.ttft_ms,
        ttft_p50_ms=percentile([t.ttft_ms for t in turns], 50),
        ttft_p95_ms=percentile([t.ttft_ms for t in turns], 95),
        decode_tps=percentile([t.decode_tps for t in turns], 50),
        prefill_tps=percentile([t.prefill_tps for t in turns], 50),
        prompt_tokens_p50=percentile([float(t.prompt_tokens) for t in turns], 50),
        size_mb=size / MIB,
        vram_mb=size_vram / MIB,
        gpu_fraction=size_vram / size if size else 0.0,
        speakable_rate=sum(is_speakable(t.text) for t in turns) / len(turns),
        length_ok_rate=sum(length_ok(t.text, c.length, config.length) for c, t in runs) / len(runs),
        correct_rate=_share([v for c, v in graded if c.category != "guardrail"]),
        guardrail_rate=_share([v for c, v in graded if c.category == "guardrail"]),
        tool_accuracy=_share(tool_results) if tools else None,
        answers=answers,
    )


TABLE_HEADERS = (
    "model",
    "params",
    "VRAM MB",
    "on GPU",
    "cold load s",
    "TTFT p50 ms",
    "TTFT p95 ms",
    "decode tok/s",
    "speakable",
    "length ok",
    "correct",
    "guardrails",
    "tools",
)


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def table_row(report: ModelReport) -> tuple[object, ...]:
    return (
        report.model,
        report.parameters,
        report.vram_mb,
        f"{report.gpu_fraction:.0%}",
        report.cold_load_ms / 1000,
        report.ttft_p50_ms,
        report.ttft_p95_ms,
        report.decode_tps,
        f"{report.speakable_rate:.0%}",
        f"{report.length_ok_rate:.0%}",
        _rate(report.correct_rate),
        _rate(report.guardrail_rate),
        _rate(report.tool_accuracy),
    )
