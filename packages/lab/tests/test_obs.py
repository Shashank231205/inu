import io
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest
import yaml

from inu.assets import sha256_of
from inu.cli import main
from inu_lab import obs
from inu_lab.obs import Stack, StackConfig, StackError, extract

REPO = Path(__file__).resolve().parents[3]
EXE_BYTES = b"pretend binary"


def zip_archive(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zipped:
        for name, data in members.items():
            zipped.writestr(name, data)
    return path


def tar_archive(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def stack_config(tmp_path: Path, **component: Any) -> StackConfig:
    spec = {
        "url": "https://example.test/tool-1.0.zip",
        "executable": "*/tool.exe",
        "args": ["--config={config}/tool.yml", "--data={data}", "--listen={tool_addr}"],
        "env": {"TOOL_HOME": "{exe_dir}"},
        "health_url": "http://{tool_addr}/ready",
        **component,
    }
    return StackConfig.model_validate(
        {
            "install_dir": tmp_path / "tools",
            "run_dir": tmp_path / "tools" / "run",
            "health_timeout_s": 1,
            "vars": {"tool_addr": "127.0.0.1:9999"},
            "components": {"tool": spec},
            "inu_env": {"INU_TELEMETRY__ENDPOINT": "http://{tool_addr}/otlp"},
        }
    )


class FakeDownloads:
    """Stands in for `datasets.download`: serves a prebuilt archive, counts calls."""

    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self.calls: list[str] = []

    def __call__(self, url: str, directory: Path) -> Path:
        self.calls.append(url)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / self.archive.name
        target.write_bytes(self.archive.read_bytes())
        return target


class FakeProcess:
    def __init__(self, exe: Path, *, running: bool = True, hangs: bool = False) -> None:
        self._exe = exe
        self._running = running
        self._hangs = hangs
        self.terminated = False
        self.killed = False

    def exe(self) -> str:
        return str(self._exe)

    def is_running(self) -> bool:
        return self._running

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        if self._hangs:
            raise psutil.TimeoutExpired(timeout)

    def kill(self) -> None:
        self.killed = True


class FakeSpawn:
    def __init__(self, pid: int = 4321, *, refuse_breakaway: bool = False) -> None:
        self.pid = pid
        self.refuse_breakaway = refuse_breakaway
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, args: list[str], cwd: Path, env: dict[str, str], log: Any, flags: int
    ) -> int:
        self.calls.append({"args": args, "cwd": cwd, "env": env, "flags": flags})
        if self.refuse_breakaway and flags & obs._WINDOWS_BREAKAWAY:
            raise PermissionError("breakaway not allowed")
        return self.pid


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    return zip_archive(tmp_path / "tool-1.0.zip", {"tool-1.0/tool.exe": EXE_BYTES})


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch, archive: Path) -> FakeDownloads:
    fake = FakeDownloads(archive)
    monkeypatch.setattr(obs, "download", fake)
    return fake


def make_stack(config: StackConfig, tmp_path: Path, status: int = 200) -> Stack:
    return Stack(config, tmp_path / "deploy", http_get=lambda url: status, sleep=lambda s: None)


def installed_stack(tmp_path: Path, **component: Any) -> tuple[Stack, Path]:
    stack = make_stack(stack_config(tmp_path, **component), tmp_path)
    exe = stack.install_dir("tool") / "tool-1.0" / "tool.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(EXE_BYTES)
    return stack, exe


# ------------------------------------------------------------------ config


def test_repo_stack_config_is_valid() -> None:
    config = StackConfig.load(REPO / "deploy" / "observability" / "stack.yaml")

    assert set(config.components) == {"prometheus", "jaeger", "grafana"}
    for spec in config.components.values():
        assert spec.archive_sha256 or spec.executable_sha256, "every binary is pinned"
        assert spec.url.startswith("https://")


def test_repo_stack_templates_all_resolve() -> None:
    path = REPO / "deploy" / "observability" / "stack.yaml"
    stack = Stack(StackConfig.load(path), path.parent)

    for name, spec in StackConfig.load(path).components.items():
        for template in [*spec.args, *spec.env.values(), spec.health_url]:
            stack.render(template, name)  # KeyError on an unknown placeholder
    assert stack.inu_env()["INU_TELEMETRY__TRACES__OTLP_ENDPOINT"].startswith("http://127.0.0.1")


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    raw = stack_config(tmp_path).model_dump(mode="json")
    raw["components"]["tool"]["surprise"] = 1

    with pytest.raises(ValueError, match="surprise"):
        StackConfig.model_validate(raw)


# ------------------------------------------------------------------ templates


def test_render_fills_paths_and_vars(tmp_path: Path) -> None:
    stack, exe = installed_stack(tmp_path)

    assert stack.render("--listen={tool_addr}", "tool") == "--listen=127.0.0.1:9999"
    assert stack.render("{config}", "tool") == str((tmp_path / "deploy").resolve())
    assert stack.render("{data}", "tool") == str(stack.data_dir("tool"))
    assert stack.render("{exe_dir}", "tool") == str(exe.parent)
    assert stack.render("{exe_home}", "tool") == str(exe.parent.parent)


def test_inu_env_uses_vars(tmp_path: Path) -> None:
    stack = make_stack(stack_config(tmp_path), tmp_path)

    assert stack.inu_env() == {"INU_TELEMETRY__ENDPOINT": "http://127.0.0.1:9999/otlp"}


# ------------------------------------------------------------------ install


def test_install_downloads_verifies_and_extracts_once(
    tmp_path: Path, archive: Path, downloads: FakeDownloads
) -> None:
    config = stack_config(tmp_path, archive_sha256=sha256_of(archive))
    stack = make_stack(config, tmp_path)

    exe = stack.install("tool")
    again = stack.install("tool")

    assert exe.read_bytes() == EXE_BYTES
    assert again == exe
    assert len(downloads.calls) == 1


def test_archive_checksum_mismatch_deletes_the_download(
    tmp_path: Path, downloads: FakeDownloads
) -> None:
    stack = make_stack(stack_config(tmp_path, archive_sha256="0" * 64), tmp_path)

    with pytest.raises(StackError, match="checksum mismatch"):
        stack.install("tool")

    assert not list((tmp_path / "tools" / "_downloads").iterdir())
    assert stack.executable("tool") is None


def test_executable_checksum_mismatch_is_refused(tmp_path: Path, downloads: FakeDownloads) -> None:
    stack = make_stack(stack_config(tmp_path, executable_sha256="0" * 64), tmp_path)

    with pytest.raises(StackError, match="executable checksum"):
        stack.install("tool")


def test_executable_checksum_match_passes(tmp_path: Path, downloads: FakeDownloads) -> None:
    exe_sha = sha256_of(_write(tmp_path / "expected.exe", EXE_BYTES))
    stack = make_stack(stack_config(tmp_path, executable_sha256=exe_sha), tmp_path)

    assert stack.install("tool").name == "tool.exe"


def test_missing_executable_after_extraction(tmp_path: Path, downloads: FakeDownloads) -> None:
    stack = make_stack(stack_config(tmp_path, executable="*/other.exe"), tmp_path)

    with pytest.raises(StackError, match=r"other.exe"):
        stack.install("tool")


def test_extract_handles_tar_gz(tmp_path: Path) -> None:
    archive = tar_archive(tmp_path / "t.tar.gz", {"pkg/bin/tool.exe": EXE_BYTES})

    extract(archive, tmp_path / "out")

    assert (tmp_path / "out" / "pkg" / "bin" / "tool.exe").read_bytes() == EXE_BYTES


def test_extract_refuses_tar_paths_outside_target(tmp_path: Path) -> None:
    archive = tar_archive(tmp_path / "evil.tar.gz", {"../escaped.txt": b"x"})

    with pytest.raises(tarfile.FilterError):
        extract(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_rejects_unknown_archive_types(tmp_path: Path) -> None:
    archive = _write(tmp_path / "tool.rar", b"x")

    with pytest.raises(StackError, match="Unsupported"):
        extract(archive, tmp_path / "out")


# ------------------------------------------------------------------ processes


def test_running_pid_rejects_a_recycled_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, _ = installed_stack(tmp_path)
    _write_pid(stack, 1234)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProcess(tmp_path / "notepad.exe"))

    assert stack.running_pid("tool") is None


def test_running_pid_accepts_our_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stack, exe = installed_stack(tmp_path)
    _write_pid(stack, 1234)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProcess(exe))

    assert stack.running_pid("tool") == 1234


def test_running_pid_handles_a_vanished_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, _ = installed_stack(tmp_path)
    _write_pid(stack, 1234)

    def gone(pid: int) -> FakeProcess:
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", gone)

    assert stack.running_pid("tool") is None


def test_start_spawns_detached_with_rendered_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, exe = installed_stack(tmp_path)
    spawn = FakeSpawn()
    monkeypatch.setattr(obs, "_spawn", spawn)

    assert stack.start("tool") == 4321

    (call,) = spawn.calls
    assert call["args"][0] == str(exe)
    assert f"--data={stack.data_dir('tool')}" in call["args"]
    assert call["env"]["TOOL_HOME"] == str(exe.parent)
    assert call["env"]["PATH"] == os.environ["PATH"]  # the parent env is kept
    assert call["cwd"].is_dir()
    assert stack.pid_file("tool").read_text("utf-8") == "4321"


@pytest.mark.skipif(os.name != "nt", reason="job objects are a Windows concept")
def test_start_falls_back_when_breakaway_is_forbidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, _ = installed_stack(tmp_path)
    spawn = FakeSpawn(refuse_breakaway=True)
    monkeypatch.setattr(obs, "_spawn", spawn)

    assert stack.start("tool") == 4321
    assert [bool(c["flags"] & obs._WINDOWS_BREAKAWAY) for c in spawn.calls] == [True, False]


def test_start_is_a_no_op_when_already_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, exe = installed_stack(tmp_path)
    _write_pid(stack, 1234)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProcess(exe))
    spawn = FakeSpawn()
    monkeypatch.setattr(obs, "_spawn", spawn)

    assert stack.start("tool") == 1234
    assert spawn.calls == []


def test_stop_terminates_then_kills_a_hung_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stack, exe = installed_stack(tmp_path)
    _write_pid(stack, 1234)
    process = FakeProcess(exe, hangs=True)
    monkeypatch.setattr(psutil, "Process", lambda pid: process)

    assert stack.stop("tool") is True
    assert process.terminated
    assert process.killed
    assert not stack.pid_file("tool").exists()


def test_stop_when_not_running(tmp_path: Path) -> None:
    stack, _ = installed_stack(tmp_path)

    assert stack.stop("tool") is False


def test_healthy_treats_connection_errors_as_unhealthy(tmp_path: Path) -> None:
    def refused(url: str) -> int:
        raise httpx.ConnectError("refused")

    stack = Stack(stack_config(tmp_path), tmp_path, http_get=refused)

    assert stack.healthy("tool") is False


def test_wait_healthy_gives_up_when_the_process_exits(tmp_path: Path) -> None:
    stack = make_stack(stack_config(tmp_path), tmp_path, status=503)  # no PID file: exited

    assert stack.wait_healthy("tool") is False


def test_wait_healthy_polls_until_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    answers = iter([503, 503, 200])
    stack = Stack(
        stack_config(tmp_path), tmp_path, http_get=lambda url: next(answers), sleep=lambda s: None
    )
    monkeypatch.setattr(stack, "running_pid", lambda name: 1234)

    assert stack.wait_healthy("tool") is True


def test_status_describes_each_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert make_stack(stack_config(tmp_path), tmp_path).status("tool").describe() == (
        "not installed"
    )
    stack, exe = installed_stack(tmp_path)
    assert stack.status("tool").describe() == "stopped"

    _write_pid(stack, 1234)
    monkeypatch.setattr(psutil, "Process", lambda pid: FakeProcess(exe))
    assert stack.status("tool").describe() == "healthy (pid 1234)"


# ------------------------------------------------------------------ CLI


def write_cli_config(tmp_path: Path) -> Path:
    path = tmp_path / "deploy" / "stack.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(stack_config(tmp_path).model_dump(mode="json")), "utf-8")
    return path


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("INU_CONFIG_DIR", str(REPO / "config"))


@pytest.mark.usefixtures("cli_env", "downloads")
def test_cli_up_starts_everything_and_prints_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_cli_config(tmp_path)
    spawn = FakeSpawn()
    monkeypatch.setattr(obs, "_spawn", spawn)
    monkeypatch.setattr(obs, "_status_code", lambda url: 200)
    monkeypatch.setattr(
        obs.Stack, "running_pid", lambda self, name: spawn.pid if spawn.calls else None
    )

    assert main(["--profile", "test", "obs", "up", "--config", str(config)]) == 0

    out = capsys.readouterr().out
    assert "healthy (pid 4321)" in out
    assert '$env:INU_TELEMETRY__ENDPOINT = "http://127.0.0.1:9999/otlp"' in out


@pytest.mark.usefixtures("cli_env", "downloads")
def test_cli_up_reports_unhealthy_components(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_cli_config(tmp_path)
    monkeypatch.setattr(obs, "_spawn", FakeSpawn())
    monkeypatch.setattr(obs, "_status_code", lambda url: 503)

    assert main(["--profile", "test", "obs", "up", "--config", str(config)]) == 1
    assert "NOT healthy" in capsys.readouterr().err


@pytest.mark.usefixtures("cli_env")
def test_cli_status_and_down_when_nothing_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_cli_config(tmp_path)

    assert main(["--profile", "test", "obs", "status", "--config", str(config)]) == 1
    assert main(["--profile", "test", "obs", "down", "--config", str(config)]) == 0

    out = capsys.readouterr().out
    assert "tool        not installed" in out
    assert "was not running" in out


@pytest.mark.usefixtures("cli_env")
def test_cli_reports_stack_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_cli_config(tmp_path)

    def broken(self: Stack, name: str) -> int:
        raise StackError("tool: archive checksum mismatch")

    monkeypatch.setattr(obs.Stack, "start", broken)

    assert main(["--profile", "test", "obs", "up", "--config", str(config)]) == 1
    assert "obs error: tool: archive checksum mismatch" in capsys.readouterr().err


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _write_pid(stack: Stack, pid: int) -> None:
    stack.pid_file("tool").parent.mkdir(parents=True, exist_ok=True)
    stack.pid_file("tool").write_text(str(pid), "utf-8")
