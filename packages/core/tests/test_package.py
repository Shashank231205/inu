import re

import inu


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", inu.__version__)
