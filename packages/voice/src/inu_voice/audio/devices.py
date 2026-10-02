"""Choosing a device from configuration."""

from inu_voice.audio.types import AudioBackend, AudioDevice, AudioDeviceError, DeviceKind


def select_device(
    backend: AudioBackend, kind: DeviceKind, host_api: str | None, name: str | None
) -> AudioDevice:
    """Find the configured device, or the host API's default when `name` is None.

    Raises AudioDeviceError naming the alternatives, so a typo in config is easy to fix.
    """
    devices = backend.devices()
    if host_api is not None and all(device.host_api != host_api for device in devices):
        apis = sorted({device.host_api for device in devices})
        raise AudioDeviceError(f"Host API {host_api!r} not found. Available: {', '.join(apis)}")

    if name is None:
        default = backend.default_device(kind, host_api)
        if default is None:
            raise AudioDeviceError(f"No default {kind} device on {host_api or 'any host API'}")
        return default

    candidates = [
        device
        for device in devices
        if device.supports(kind) and (host_api is None or device.host_api == host_api)
    ]
    for device in candidates:
        if name.lower() in device.name.lower():
            return device
    listing = "; ".join(device.describe() for device in candidates) or "none"
    raise AudioDeviceError(f"No {kind} device matching {name!r}. Available: {listing}")
