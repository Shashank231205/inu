import os
from collections.abc import Callable
from pathlib import Path

import pytest

ConfigDirFactory = Callable[[str, dict[str, str]], Path]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's own INU_* variables and .env out of every test."""
    for name in [n for n in os.environ if n.startswith("INU_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def repo_config_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "config"


@pytest.fixture
def make_config_dir(tmp_path: Path) -> ConfigDirFactory:
    """Build a throwaway config dir from a base YAML string and {profile: YAML}."""

    def make(base: str, profiles: dict[str, str]) -> Path:
        root = tmp_path / "config"
        (root / "profiles").mkdir(parents=True)
        (root / "base.yaml").write_text(base, encoding="utf-8")
        for name, body in profiles.items():
            (root / "profiles" / f"{name}.yaml").write_text(body, encoding="utf-8")
        return root

    return make
