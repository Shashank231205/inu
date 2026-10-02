import json
import math
from pathlib import Path

from inu_lab.results import markdown_table, percentile, save_results


def test_percentile_handles_empty_input() -> None:
    assert math.isnan(percentile([], 50))
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0


def test_save_results_writes_timestamped_json(tmp_path: Path) -> None:
    path = save_results("llm", {"models": [{"name": "x"}]}, tmp_path / "out")
    assert path.name.endswith("-llm.json")
    assert json.loads(path.read_text("utf-8")) == {"models": [{"name": "x"}]}


def test_markdown_table_formats_numbers_and_gaps() -> None:
    table = markdown_table(
        ["a", "b", "c", "d"], [["m", 1234.567, 0.123, None], ["n", math.nan, 5, "x"]]
    )
    lines = table.splitlines()
    assert lines[0] == "| a | b | c | d |"
    assert lines[1] == "|---|---|---|---|"
    assert lines[2] == "| m | 1234.6 | 0.12 | - |"
    assert lines[3] == "| n | - | 5 | x |"
