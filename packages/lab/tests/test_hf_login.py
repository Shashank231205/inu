import pytest
import truststore

from inu_lab import hf_login


def test_login_runs_with_the_system_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: calls.append("trust"))
    monkeypatch.setattr(
        hf_login, "login", lambda skip_if_logged_in: calls.append(f"login:{skip_if_logged_in}")
    )

    hf_login.main()

    assert calls == ["trust", "login:False"]  # trust store first, then always prompt
