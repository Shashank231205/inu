"""Test doubles for benchmark backends."""

from collections.abc import Iterator
from typing import Any


class FakeOllama:
    """Streams a canned reply; tool prompts get a canned tool call."""

    def __init__(self, capabilities: list[str] | None = None) -> None:
        self.capabilities = capabilities or ["completion", "tools", "thinking"]
        self.loaded: list[str] = ["some-other-model"]
        self.unloaded: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        think: bool | None,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "think": think,
                "options": options,
            }
        )
        if model not in self.loaded:
            self.loaded.append(model)
        prompt = messages[-1]["content"]
        if tools and "timer" in prompt:
            yield {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "set_timer", "arguments": {"minutes": 7}}}
                    ],
                }
            }
        else:
            yield {"message": {"content": "Canberra is "}}
            yield {"message": {"content": "the capital."}}
        yield {
            "message": {"content": ""},
            "done": True,
            "load_duration": 2_000_000_000,
            "prompt_eval_count": 50,
            "prompt_eval_duration": 25_000_000,
            "eval_count": 40,
            "eval_duration": 500_000_000,
        }

    def show(self, model: str) -> dict[str, Any]:
        return {
            "capabilities": self.capabilities,
            "details": {"family": "qwen", "parameter_size": "4B", "quantization_level": "Q4_K_M"},
        }

    def running(self) -> list[dict[str, Any]]:
        # Like Ollama, report untagged names with ":latest".
        return [
            {"name": m if ":" in m else f"{m}:latest", "size": 4 * 2**30, "size_vram": 3 * 2**30}
            for m in self.loaded
        ]

    def unload(self, model: str) -> None:
        self.unloaded.append(model)
        bare = model.removesuffix(":latest")
        for name in (model, bare):
            if name in self.loaded:
                self.loaded.remove(name)
