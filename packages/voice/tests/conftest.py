import os
from pathlib import Path

import pytest

REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's own INU_* variables and .env out of every test."""
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def repo_config_dir() -> Path:
    return REPO_CONFIG_DIR
