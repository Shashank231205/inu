import ssl

import pytest
import truststore

from inu import net
from inu.config import NetworkSettings


def settings(system: bool) -> NetworkSettings:
    return NetworkSettings(system_trust_store=system, download_timeout_s=5)


def test_system_trust_store_is_injected_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: calls.append("inject"))

    net.configure_tls(settings(system=True))
    net.configure_tls(settings(system=False))

    assert calls == ["inject"]


def test_ssl_context_follows_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    default = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(ssl, "create_default_context", lambda: default)

    assert isinstance(net.ssl_context(settings(system=True)), truststore.SSLContext)
    assert net.ssl_context(settings(system=False)) is default
