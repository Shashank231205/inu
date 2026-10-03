"""`inu audio`: list devices and benchmark audio I/O. Registered as a CLI plugin."""

import argparse
import asyncio
import os

from inu.config import Settings
from inu.observability import init_observability
from inu_voice.audio import AudioBackend, AudioDeviceError, AudioEngine, DeviceKind, select_device
from inu_voice.audio.bench import BenchReport, run_bench
from inu_voice.audio.sounddevice_backend import SoundDeviceBackend

EXIT_DEVICE_ERROR = 3


def make_backend() -> AudioBackend:
    return SoundDeviceBackend()


class AudioCommand:
    name = "audio"
    help = "List audio devices and benchmark audio I/O"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="audio_action", required=True)
        actions.add_parser("devices", help="List devices and show which ones config selects")
        bench = actions.add_parser("bench", help="Capture and play under load; count dropouts")
        bench.add_argument("--seconds", type=float, default=30.0)
        bench.add_argument(
            "--cpu-load",
            type=float,
            default=0.8,
            help="Fraction of logical cores to keep busy in other processes",
        )
        bench.add_argument(
            "--gil-load", action="store_true", help="Also spin a pure-Python thread in-process"
        )

    def run(self, args: argparse.Namespace, settings: Settings) -> int:
        backend = make_backend()
        try:
            if args.audio_action == "devices":
                print(render_devices(backend, settings))
                return 0
            telemetry = init_observability(settings)  # xrun counters reach the dashboards
            burners = round((os.cpu_count() or 1) * args.cpu_load)
            try:
                report = asyncio.run(
                    _bench(settings, backend, args.seconds, burners, args.gil_load)
                )
            finally:
                telemetry.shutdown()
        except AudioDeviceError as exc:
            print(f"audio error: {exc.message}")
            return EXIT_DEVICE_ERROR
        print(report.render())
        return 0 if report.passed else 1


async def _bench(
    settings: Settings, backend: AudioBackend, seconds: float, burners: int, gil_load: bool
) -> BenchReport:
    async with AudioEngine(settings.audio, backend) as engine:
        return await run_bench(engine, seconds=seconds, cpu_burners=burners, gil_load=gil_load)


def render_devices(backend: AudioBackend, settings: Settings) -> str:
    audio = settings.audio
    selected: dict[int, list[str]] = {}
    for kind, direction in ((DeviceKind.INPUT, audio.input), (DeviceKind.OUTPUT, audio.output)):
        try:
            device = select_device(backend, kind, audio.host_api, direction.device)
            selected.setdefault(device.index, []).append(f"<- {kind}")
        except AudioDeviceError as exc:
            selected.setdefault(-1, []).append(f"{kind}: {exc.message}")

    lines = [f"{'#':>3}  {'host API':<20} {'in':>2} {'out':>3} {'rate':>6}  name"]
    for device in backend.devices():
        marks = " ".join(selected.get(device.index, []))
        lines.append(
            f"{device.index:>3}  {device.host_api:<20} {device.max_input_channels:>2}"
            f" {device.max_output_channels:>3} {device.default_sample_rate:>6}  {device.name}"
            + (f"  {marks}" if marks else "")
        )
    lines.extend(selected.get(-1, []))
    return "\n".join(lines)
