"""Model files and other large downloads.

Each asset is pinned by URL and SHA-256 in config. It is downloaded into a `.part`
file, verified, then renamed into place, so a file at the final path is always
complete and verified. Later loads trust that file: hashing a large model on every
start would cost seconds. The pinned version belongs in the path, so a new pin
downloads a new file instead of reusing the old one.

Interrupted downloads resume from the `.part` file with an HTTP Range request. On a
slow connection a 470 MB release can take half an hour, and starting over after every
interruption would mean it never finishes.
"""

import hashlib
import ssl
from pathlib import Path

import httpx
import structlog

from inu.config import ModelAsset, NetworkSettings
from inu.errors import ErrorCategory, InuError
from inu.net import ssl_context

_CHUNK = 1 << 20
_RANGE_NOT_SATISFIABLE = 416

log = structlog.get_logger(__name__)


class AssetDownloadError(InuError):
    code = "asset.download_failed"
    category = ErrorCategory.PROVIDER
    retryable = True


class AssetChecksumError(InuError):
    code = "asset.checksum_mismatch"
    category = ErrorCategory.VALIDATION


def ensure_asset(
    asset: ModelAsset,
    data_dir: Path,
    network: NetworkSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Path:
    """Return the asset's local path, downloading and verifying it first if needed."""
    target = data_dir / asset.path
    if target.is_file():
        return target
    url = str(asset.url)
    partial = fetch(
        url,
        target,
        timeout_s=network.download_timeout_s,
        verify=ssl_context(network),
        transport=transport,
        keep_partial=True,
    )
    actual = sha256_of(partial)
    if actual != asset.sha256:
        partial.unlink()
        raise AssetChecksumError(
            f"{url} does not match the pinned SHA-256; the download was deleted",
            context={"expected": asset.sha256, "actual": actual},
        )
    partial.replace(target)
    return target


def fetch(
    url: str,
    target: Path,
    *,
    timeout_s: float,
    verify: ssl.SSLContext | bool = True,
    transport: httpx.BaseTransport | None = None,
    keep_partial: bool = False,
) -> Path:
    """Download `url` to `target`, resuming an earlier partial download.

    Returns `target`, or with `keep_partial` the complete `.part` file, so the caller
    can verify it before it takes the final name.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    with httpx.Client(
        transport=transport, verify=verify, follow_redirects=True, timeout=timeout_s
    ) as client:
        try:
            if not _stream_into(client, url, partial):
                partial.unlink()  # the server rejected our offset; start over once
                _stream_into(client, url, partial)
        except httpx.HTTPError as exc:
            # The partial file stays: the next attempt resumes from it.
            raise AssetDownloadError(f"Could not download {url}: {exc}") from exc
    if keep_partial:
        return partial
    partial.replace(target)
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_into(client: httpx.Client, url: str, partial: Path) -> bool:
    """Append the rest of `url` to `partial`. False if the server refused the range."""
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers) as response:
        if offset and response.status_code == _RANGE_NOT_SATISFIABLE:
            return False
        response.raise_for_status()
        resumed = offset > 0 and response.status_code == httpx.codes.PARTIAL_CONTENT
        log.info("asset.download", url=url, resumed_from=offset if resumed else 0)
        with partial.open("ab" if resumed else "wb") as out:
            for chunk in response.iter_bytes(_CHUNK):
                out.write(chunk)
    return True
