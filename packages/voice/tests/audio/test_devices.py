import pytest

from inu_voice.audio import AudioDeviceError, DeviceKind, select_device
from voice_fakes import MME, WASAPI, FakeBackend


def test_default_device_of_the_chosen_host_api() -> None:
    backend = FakeBackend()
    assert select_device(backend, DeviceKind.INPUT, WASAPI, None).name == "Microphone Array"
    assert select_device(backend, DeviceKind.OUTPUT, None, None).host_api == MME


def test_name_match_is_a_case_insensitive_substring() -> None:
    device = select_device(FakeBackend(), DeviceKind.OUTPUT, WASAPI, "usb headset")
    assert device.name == "USB Headset"


def test_name_match_respects_direction_and_host_api() -> None:
    backend = FakeBackend()
    assert select_device(backend, DeviceKind.INPUT, WASAPI, "USB").name == "USB Headset Mic"
    with pytest.raises(AudioDeviceError):
        select_device(backend, DeviceKind.INPUT, MME, "Array")


def test_unknown_host_api_lists_the_real_ones() -> None:
    with pytest.raises(AudioDeviceError, match=r"'ASIO' not found\. Available: MME, Windows"):
        select_device(FakeBackend(), DeviceKind.INPUT, "ASIO", None)


def test_unknown_device_lists_candidates() -> None:
    with pytest.raises(AudioDeviceError, match=r"No input device matching 'Blue Yeti'.*Array"):
        select_device(FakeBackend(), DeviceKind.INPUT, WASAPI, "Blue Yeti")


def test_missing_default_is_an_error() -> None:
    backend = FakeBackend(defaults={})
    with pytest.raises(AudioDeviceError, match="No default output device on Windows WASAPI"):
        select_device(backend, DeviceKind.OUTPUT, WASAPI, None)


def test_error_belongs_to_the_device_category() -> None:
    error = AudioDeviceError("gone")
    assert error.attributes()["error.category"] == "device"
    assert error.attributes()["error.retryable"] is True
