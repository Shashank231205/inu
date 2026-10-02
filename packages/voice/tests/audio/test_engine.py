import sys

import pytest

from inu_voice.audio import AudioDeviceError, AudioEngine, DeviceKind
from inu_voice.audio.engine import _observe_xruns
from voice_fakes import WASAPI, FakeBackend, FakeClock, audio_settings, device, eventually


async def test_opens_host_api_defaults_at_native_rate_with_configured_blocks() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend, clock=FakeClock()) as engine:
        (mic,), (speaker,) = backend.inputs, backend.outputs
        assert (mic.device.name, mic.rate, mic.block) == ("Microphone Array", 48_000, 480)
        assert (speaker.device.name, speaker.rate) == ("Speakers (Realtek)", 48_000)
        assert engine.healthy()
    assert mic.closed
    assert speaker.closed


async def test_shortens_the_gil_switch_interval_while_running() -> None:
    before = sys.getswitchinterval()
    async with AudioEngine(audio_settings(gil_switch_interval_ms=0.5), FakeBackend()):
        assert sys.getswitchinterval() == pytest.approx(0.0005)
    assert sys.getswitchinterval() == before


async def test_failed_start_restores_the_gil_switch_interval() -> None:
    before = sys.getswitchinterval()
    engine = AudioEngine(audio_settings(input={"device": "nope"}), FakeBackend())
    with pytest.raises(AudioDeviceError):
        await engine.start()
    assert sys.getswitchinterval() == before


async def test_uses_configured_devices_and_rates() -> None:
    backend = FakeBackend()
    settings = audio_settings(
        input={"device": "usb", "sample_rate": 16_000}, output={"device": "headset"}
    )
    async with AudioEngine(settings, backend, clock=FakeClock()) as engine:
        assert backend.inputs[0].device.name == "USB Headset Mic"
        assert backend.inputs[0].rate == 16_000
        assert engine.devices[DeviceKind.OUTPUT][0].name == "USB Headset"


async def test_missing_configured_device_fails_start_and_leaks_nothing() -> None:
    backend = FakeBackend()
    engine = AudioEngine(audio_settings(output={"device": "Blue Yeti"}), backend)
    with pytest.raises(AudioDeviceError, match="Blue Yeti"):
        await engine.start()
    assert all(stream.closed for stream in backend.inputs + backend.outputs)


async def test_reconnects_when_a_stream_stops() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend, clock=FakeClock()) as engine:
        backend.inputs[0].active = False

        await eventually(lambda: engine.reconnects == 1)

        assert backend.rescans == 1
        assert len(backend.inputs) == len(backend.outputs) == 2
        assert backend.inputs[0].closed
        assert backend.outputs[0].closed
        assert engine.healthy()


async def test_reconnects_when_callbacks_stall() -> None:
    clock = FakeClock()
    backend = FakeBackend()
    async with AudioEngine(audio_settings(stall_timeout_ms=500), backend, clock=clock) as engine:
        clock.advance_ms(600)  # streams claim to be active but deliver nothing
        await eventually(lambda: engine.reconnects == 1)


async def test_falls_back_to_default_when_configured_device_disappears() -> None:
    backend = FakeBackend()
    settings = audio_settings(input={"device": "USB Headset Mic"})
    async with AudioEngine(settings, backend, clock=FakeClock()) as engine:
        backend.unplug("USB Headset Mic")
        backend.inputs[-1].active = False

        await eventually(lambda: engine.reconnects == 1)

        assert engine.devices[DeviceKind.INPUT][0].name == "Microphone Array"


async def test_keeps_retrying_until_devices_come_back() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend, clock=FakeClock()) as engine:
        backend.unplug("Speakers (Realtek)")
        backend.defaults.pop((DeviceKind.OUTPUT, WASAPI))
        backend.outputs[-1].active = False
        await eventually(lambda: backend.rescans >= 3)
        assert engine.reconnects == 0

        backend.replug(device(9, "Speakers (Realtek)", WASAPI, outputs=2))
        backend.defaults[(DeviceKind.OUTPUT, WASAPI)] = 9
        await eventually(lambda: engine.reconnects == 1)


async def test_xrun_metrics_report_both_directions() -> None:
    backend = FakeBackend()
    async with AudioEngine(audio_settings(), backend, clock=FakeClock()) as engine:
        engine.microphone.stats.xruns = 2
        engine.speaker.stats.device_xruns = 1
        observations = {
            (o.attributes["direction"], o.attributes["source"]): o.value
            for o in _observe_xruns(None)  # type: ignore[arg-type]
            if o.attributes is not None
        }
    assert observations[("input", "buffer")] >= 2
    assert observations[("output", "device")] >= 1
