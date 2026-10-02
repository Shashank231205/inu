# inu-voice

INU's real-time voice layer. It runs on the laptop only; the always-on VM never installs it.

- `inu_voice.audio`: microphone capture and speaker playback over lock-free ring buffers, with streaming resampling and device reconnects.
