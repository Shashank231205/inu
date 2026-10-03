"""Local observability stack as native processes: Prometheus, Jaeger, Grafana.

The laptop runs no containers (ADR 0007), so each component is a pinned release that
is downloaded once, verified by SHA-256, extracted under `data/tools`, and started as a
detached process with a PID file and a log file. Stopping checks that the PID still
belongs to the expected executable, so a recycled PID never kills something else.
"""

import argparse
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Self

import httpx
import psutil
import yaml
from pydantic import BaseModel, ConfigDict, Field

from inu.assets import sha256_of
from inu.config import Settings
from inu.errors import ErrorCategory, InuError
from inu_lab.datasets import download

DEFAULT_CONFIG = Path("deploy/observability/stack.yaml")
_WINDOWS_DETACHED = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
# Terminals and IDEs often run shells inside a kill-on-close job object; without
# breaking away, the stack dies with the terminal that started it.
_WINDOWS_BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB


class StackError(InuError):
    code = "obs.stack_error"
    category = ErrorCategory.CONFIG


class ComponentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    archive_sha256: str | None = None
    executable: str = Field(description="Glob, relative to the component's install dir")
    executable_sha256: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    health_url: str


class StackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    install_dir: Path
    run_dir: Path
    health_timeout_s: float = Field(gt=0)
    vars: dict[str, str]
    components: dict[str, ComponentSpec] = Field(min_length=1)
    inu_env: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ComponentStatus:
    name: str
    installed: bool
    pid: int | None
    healthy: bool

    def describe(self) -> str:
        if not self.installed:
            return "not installed"
        if self.pid is None:
            return "stopped"
        return f"{'healthy' if self.healthy else 'running, not healthy'} (pid {self.pid})"


def extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(target)  # noqa: S202 - zipfile strips absolute paths and ".."
    elif archive.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(target, filter="data")  # refuses paths outside target
    else:
        raise StackError(f"Unsupported archive type: {archive.name}")


class Stack:
    def __init__(
        self,
        config: StackConfig,
        config_dir: Path,
        *,
        http_get: Callable[[str], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._config_dir = config_dir.resolve()
        self._http_get = http_get or _status_code
        self._sleep = sleep

    @property
    def names(self) -> list[str]:
        return list(self._config.components)

    # ------------------------------------------------------------------ paths

    def install_dir(self, name: str) -> Path:
        return (self._config.install_dir / name).resolve()

    def data_dir(self, name: str) -> Path:
        return (self._config.run_dir / name).resolve()

    def pid_file(self, name: str) -> Path:
        return self._config.run_dir.resolve() / f"{name}.pid"

    def log_file(self, name: str) -> Path:
        return self._config.run_dir.resolve() / f"{name}.log"

    def executable(self, name: str) -> Path | None:
        spec = self._config.components[name]
        matches = sorted(self.install_dir(name).glob(spec.executable))
        return matches[0] if matches else None

    def render(self, template: str, name: str) -> str:
        exe = self.executable(name)
        values = {
            **self._config.vars,
            "config": str(self._config_dir),
            "data": str(self.data_dir(name)),
            "install": str(self.install_dir(name)),
            "exe_dir": str(exe.parent) if exe else "",
            # Release root for layouts with the binary in bin/ (Grafana needs it as is,
            # it does not resolve "bin/..").
            "exe_home": str(exe.parent.parent) if exe else "",
        }
        return template.format_map(values)

    def inu_env(self) -> dict[str, str]:
        values = {**self._config.vars, "config": str(self._config_dir)}
        return {key: value.format_map(values) for key, value in self._config.inu_env.items()}

    # ------------------------------------------------------------------ lifecycle

    def install(self, name: str) -> Path:
        """Download, verify and extract once. Returns the executable."""
        spec = self._config.components[name]
        existing = self.executable(name)
        if existing is not None:
            return existing
        archive = download(spec.url, self._config.install_dir.resolve() / "_downloads")
        if spec.archive_sha256 and sha256_of(archive) != spec.archive_sha256:
            archive.unlink()
            raise StackError(f"{name}: archive checksum mismatch; deleted the download")
        extract(archive, self.install_dir(name))
        exe = self.executable(name)
        if exe is None:
            raise StackError(f"{name}: no file matching {spec.executable!r} after extraction")
        if spec.executable_sha256 and sha256_of(exe) != spec.executable_sha256:
            raise StackError(f"{name}: executable checksum mismatch at {exe}")
        return exe

    def running_pid(self, name: str) -> int | None:
        pid_file = self.pid_file(name)
        exe = self.executable(name)
        if not pid_file.is_file() or exe is None:
            return None
        pid = int(pid_file.read_text("utf-8").strip())
        try:
            process = psutil.Process(pid)
            same_binary = Path(process.exe()).resolve() == exe.resolve()
        except (psutil.Error, OSError):
            return None
        return pid if same_binary and process.is_running() else None

    def start(self, name: str) -> int:
        running = self.running_pid(name)
        if running is not None:
            return running
        exe = self.install(name)
        spec = self._config.components[name]
        self.data_dir(name).mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **{k: self.render(v, name) for k, v in spec.env.items()}}
        args = [str(exe), *(self.render(a, name) for a in spec.args)]
        with self.log_file(name).open("ab") as log:
            if sys.platform != "win32":
                pid = _spawn(args, self.data_dir(name), env, log, flags=0)
            else:
                try:
                    pid = _spawn(
                        args, self.data_dir(name), env, log, _WINDOWS_DETACHED | _WINDOWS_BREAKAWAY
                    )
                except PermissionError:  # the parent's job forbids breakaway
                    pid = _spawn(args, self.data_dir(name), env, log, _WINDOWS_DETACHED)
        self.pid_file(name).write_text(str(pid), "utf-8")
        return pid

    def stop(self, name: str) -> bool:
        pid = self.running_pid(name)
        self.pid_file(name).unlink(missing_ok=True)
        if pid is None:
            return False
        process = psutil.Process(pid)
        process.terminate()
        try:
            process.wait(timeout=15)
        except psutil.TimeoutExpired:
            process.kill()
        return True

    def healthy(self, name: str) -> bool:
        url = self.render(self._config.components[name].health_url, name)
        try:
            return self._http_get(url) == 200
        except httpx.HTTPError:
            return False

    def wait_healthy(self, name: str) -> bool:
        deadline = time.monotonic() + self._config.health_timeout_s
        while time.monotonic() < deadline:
            if self.healthy(name):
                return True
            if self.running_pid(name) is None:
                return False  # exited; its log says why
            self._sleep(0.5)
        return False

    def status(self, name: str) -> ComponentStatus:
        pid = self.running_pid(name)
        return ComponentStatus(
            name=name,
            installed=self.executable(name) is not None,
            pid=pid,
            healthy=pid is not None and self.healthy(name),
        )


def _spawn(args: list[str], cwd: Path, env: dict[str, str], log: IO[bytes], flags: int) -> int:
    process = subprocess.Popen(  # noqa: S603 - pinned, checksum-verified binary
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )
    return process.pid


def _status_code(url: str) -> int:
    return httpx.get(url, timeout=2).status_code


# ------------------------------------------------------------------ CLI


class ObsCommand:
    name = "obs"
    help = "Local observability stack: Prometheus, Jaeger, Grafana (native, no containers)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("action", choices=["up", "down", "status"])
        parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
        stack = Stack(StackConfig.load(args.config), args.config.parent)
        try:
            if args.action == "up":
                return _up(stack)
            if args.action == "down":
                for name in reversed(stack.names):
                    print(f"{name:<11} {'stopped' if stack.stop(name) else 'was not running'}")
                return 0
            return _print_status(stack)
        except StackError as exc:
            print(f"obs error: {exc.message}", file=sys.stderr)
            return 1


def _up(stack: Stack) -> int:
    for name in stack.names:
        print(f"{name:<11} starting (pid {stack.start(name)})", flush=True)
    failed = [name for name in stack.names if not stack.wait_healthy(name)]
    for name in failed:
        print(f"{name:<11} NOT healthy; see {stack.log_file(name)}", file=sys.stderr)
    _print_status(stack)
    print("\nSend INU telemetry here (PowerShell):")
    for key, value in stack.inu_env().items():
        print(f'  $env:{key} = "{value}"')
    return 1 if failed else 0


def _print_status(stack: Stack) -> int:
    rows = [stack.status(name) for name in stack.names]
    for row in rows:
        print(f"{row.name:<11} {row.describe()}")
    return 0 if all(row.healthy for row in rows) else 1
