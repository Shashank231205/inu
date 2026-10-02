"""Describe the machine a benchmark ran on, so results stay interpretable later."""

import os
import platform
import shutil
import subprocess


def gpu_memory_used_mb() -> float | None:
    out = _nvidia_smi("memory.used")
    return float(out) if out else None


def describe_machine() -> dict[str, object]:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor(),
        "logical_cores": os.cpu_count(),
        "gpu": _nvidia_smi("name"),
        "gpu_memory_mb": _nvidia_smi("memory.total"),
        "gpu_driver": _nvidia_smi("driver_version"),
        "python": platform.python_version(),
    }


def _nvidia_smi(field: str) -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments
            [executable, f"--query-gpu={field}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip().splitlines()[0].strip() or None
