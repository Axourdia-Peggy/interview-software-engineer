"""End to end: the shipped examples through both front ends.

Every package is written under pytest's tmp_path, never to the repository's
output/ folder.
"""

from __future__ import annotations

import pytest

from shiftforge.api import generate_schedule
from shiftforge.cli import main

from .conftest import EXAMPLES_DIR

EXAMPLES = ["clinic_week", "ward_tight", "pharmacy_relief"]
PACKAGE_FILES = ["roster.csv", "roster.json", "validation.txt", "run_summary.json"]


@pytest.mark.parametrize("example", EXAMPLES)
def test_example_converges_via_cli(example, tmp_path, capsys):
    # The pass line of the task: exit code 0, converged, no hard violation.
    exit_code = main([str(EXAMPLES_DIR / f"{example}.json"), "--output-dir", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "converged      : True" in out
    assert "hard violations: 0" in out

    package = tmp_path / example
    for name in PACKAGE_FILES:
        assert (package / name).is_file(), name
    assert (package / "validation.txt").read_text(encoding="utf-8").startswith("verdict: PASS")


@pytest.mark.parametrize("example", EXAMPLES)
def test_cli_and_api_write_identical_packages(example, tmp_path):
    # The spec requires both front ends to give exactly the same result for the
    # same input. This only checks that they agree, not that they are right.
    spec_path = EXAMPLES_DIR / f"{example}.json"
    cli_dir, api_dir = tmp_path / "cli", tmp_path / "api"

    main([str(spec_path), "--output-dir", str(cli_dir)])
    generate_schedule(spec_path, output_dir=api_dir)

    for name in PACKAGE_FILES:
        cli_bytes = (cli_dir / example / name).read_bytes()
        api_bytes = (api_dir / example / name).read_bytes()
        assert cli_bytes == api_bytes, name


# --- each example shows the behaviour Configuration-Schema.md describes -----


def test_clinic_week_converges_on_the_first_strategy():
    # "人力寬裕，第一個策略即可收斂"
    summary = generate_schedule(EXAMPLES_DIR / "clinic_week.json", write_output=False)

    assert summary["converged"]
    assert summary["iterations"] == 1
    assert summary["strategies_tried"] == ["balanced_rotation"]


def test_ward_tight_needs_a_strategy_switch():
    # "需要切換策略才能收斂"
    summary = generate_schedule(EXAMPLES_DIR / "ward_tight.json", write_output=False)

    assert summary["converged"]
    assert summary["hard_violations"] == 0
    assert len(summary["strategies_tried"]) > 1


def test_pharmacy_relief_reports_uneven_workload(tmp_path):
    # "人力充裕但工作量分配不均": P09 and P10 only hold the nurse role, so they get
    # fewer shifts and fall below the weekly hour floor. Before the R006 key fix
    # this example reported no soft violation at all.
    summary = generate_schedule(EXAMPLES_DIR / "pharmacy_relief.json", output_dir=tmp_path)

    assert summary["converged"]
    assert summary["hard_violations"] == 0
    assert summary["soft_violations"] > 0

    report = (tmp_path / "pharmacy_relief" / "validation.txt").read_text(encoding="utf-8")
    assert "[SOFT] R006 weekly_hours: P09" in report
    assert "[SOFT] R006 weekly_hours: P10" in report
