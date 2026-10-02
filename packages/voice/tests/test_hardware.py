"""Runs against the real microphone and speaker. Opt in with INU_TEST_HARDWARE=1."""

import asyncio
import os
from pathlib import Path

import numpy as np
import pytest

from inu.config import load_settings
from inu_voice.audio import AudioEngine
from inu_voice.audio.sounddevice_backend import SoundDeviceBackend

# Read at import: the isolation fixture strips INU_* variables before tests run.
ENABLED = os.environ.get("INU_TEST_HARDWARE") == "1"

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(not ENABLED, reason="set INU_TEST_HARDWARE=1 to use real audio devices"),
]


async def test_real_devices_capture_and_play(repo_config_dir: Path) -> None:
    settings = load_settings(profile="laptop", config_dir=repo_config_dir, environ={})
    async with AudioEngine(settings.audio, SoundDeviceBackend()) as engine:
        frames = 0

        async def capture() -> None:
            nonlocal frames
            async for _ in engine.microphone.frames():
                frames += 1
                if frames == 25:  # half a second
                    return

        await asyncio.wait_for(capture(), timeout=5)
        await engine.speaker.play(np.zeros(4_800, dtype=np.float32), 24_000)
        await asyncio.wait_for(engine.speaker.drain(), timeout=5)

        assert engine.healthy()
        assert engine.microphone.stats.xruns == 0
