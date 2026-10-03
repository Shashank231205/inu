import hashlib
from pathlib import Path

import httpx
import pytest

from inu.assets import AssetChecksumError, AssetDownloadError, ensure_asset, fetch
from inu.config import ModelAsset, NetworkSettings

PAYLOAD = b"model weights" * 1000
NETWORK = NetworkSettings(system_trust_store=False, download_timeout_s=5)


def asset(sha256: str = hashlib.sha256(PAYLOAD).hexdigest()) -> ModelAsset:
    return ModelAsset.model_validate(
        {"path": "models/m/v1/m.onnx", "url": "https://models.test/m.onnx", "sha256": sha256}
    )


def serving(status: int = 200, body: bytes = PAYLOAD) -> tuple[httpx.MockTransport, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler), seen


def test_downloads_verifies_and_places_the_file(tmp_path: Path) -> None:
    transport, seen = serving()

    path = ensure_asset(asset(), tmp_path, NETWORK, transport=transport)

    assert path == tmp_path / "models" / "m" / "v1" / "m.onnx"
    assert path.read_bytes() == PAYLOAD
    assert seen == ["https://models.test/m.onnx"]
    assert not list(path.parent.glob("*.part"))


def test_an_existing_file_is_not_downloaded_again(tmp_path: Path) -> None:
    transport, seen = serving()
    ensure_asset(asset(), tmp_path, NETWORK, transport=transport)

    ensure_asset(asset(), tmp_path, NETWORK, transport=transport)

    assert len(seen) == 1


def test_checksum_mismatch_leaves_nothing_behind(tmp_path: Path) -> None:
    transport, _ = serving(body=b"tampered")

    with pytest.raises(AssetChecksumError, match="pinned SHA-256") as caught:
        ensure_asset(asset(), tmp_path, NETWORK, transport=transport)

    assert caught.value.context["actual"] == hashlib.sha256(b"tampered").hexdigest()
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_http_errors_are_retryable_download_errors(tmp_path: Path) -> None:
    transport, _ = serving(status=503)

    with pytest.raises(AssetDownloadError) as caught:
        ensure_asset(asset(), tmp_path, NETWORK, transport=transport)

    assert caught.value.retryable
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_sha256_must_be_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="sha256"):
        asset(sha256="ABC")


def test_an_interrupted_download_resumes_with_a_range_request(tmp_path: Path) -> None:
    target = tmp_path / "models" / "m" / "v1" / "m.onnx"
    target.parent.mkdir(parents=True)
    (target.parent / "m.onnx.part").write_bytes(PAYLOAD[:1000])
    ranges: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("range"))
        return httpx.Response(206, content=PAYLOAD[1000:])

    path = ensure_asset(asset(), tmp_path, NETWORK, transport=httpx.MockTransport(handler))

    assert ranges == ["bytes=1000-"]
    assert path.read_bytes() == PAYLOAD


def test_a_server_ignoring_the_range_restarts_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(b"stale")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PAYLOAD)  # full body, not 206

    fetch("https://x.test/file.bin", target, timeout_s=5, transport=httpx.MockTransport(handler))

    assert target.read_bytes() == PAYLOAD


def test_a_rejected_range_starts_over(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    (tmp_path / "file.bin.part").write_bytes(PAYLOAD + b"extra")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("range"):
            return httpx.Response(416)
        return httpx.Response(200, content=PAYLOAD)

    fetch("https://x.test/file.bin", target, timeout_s=5, transport=httpx.MockTransport(handler))

    assert target.read_bytes() == PAYLOAD


def test_a_failed_download_keeps_its_partial_for_next_time(tmp_path: Path) -> None:
    partial = tmp_path / "f.part"
    partial.write_bytes(PAYLOAD[:1000])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("stalled", request=request)

    with pytest.raises(AssetDownloadError):
        fetch(
            "https://x.test/f", tmp_path / "f", timeout_s=5, transport=httpx.MockTransport(handler)
        )

    assert partial.read_bytes() == PAYLOAD[:1000]
