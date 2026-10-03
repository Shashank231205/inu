"""Process-wide network policy.

On machines where antivirus or a proxy re-signs HTTPS, certifi's CA bundle rejects
every connection, while the OS trust store accepts it. Third-party libraries (the
Hugging Face hub, model downloaders) build their own HTTP clients, so the choice is
applied once per process to the `ssl` module rather than per client.
"""

import ssl

import truststore

from inu.config import NetworkSettings


def configure_tls(network: NetworkSettings) -> None:
    if network.system_trust_store:
        truststore.inject_into_ssl()


def ssl_context(network: NetworkSettings) -> ssl.SSLContext:
    """A client context following the configured trust policy, for INU's own clients."""
    if network.system_trust_store:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()
