"""Convergence decision loop."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shiftforge.engine import run
from shiftforge.spec_parser import parse_spec

from .conftest import EXAMPLES_DIR


@pytest.fixture
def ward_tight(catalogs):
    # All three catalog strategies apply to it, and the first two cannot satisfy
    # it, so the loop keeps switching for as long as it is allowed to.
    return parse_spec(EXAMPLES_DIR / "ward_tight.json", catalogs)


@pytest.mark.parametrize(
    ("allowed_switches", "expected_strategies"),
    [
        (0, ["balanced_rotation"]),
        (1, ["balanced_rotation", "seniority_first"]),
        (2, ["balanced_rotation", "seniority_first", "coverage_first"]),
        (5, ["balanced_rotation", "seniority_first", "coverage_first"]),  # only 3 exist
    ],
)
def test_n_switches_allow_n_plus_one_strategies(
    catalogs, ward_tight, allowed_switches, expected_strategies
):
    # Regression: the guard used '>=' on the zero-based candidate index, so it
    # stopped one strategy short (and with 0 switches it tried no strategy at all).
    spec = replace(ward_tight, max_strategy_switches=allowed_switches)
    result = run(spec, catalogs)

    assert result.strategies_tried == expected_strategies
    ran = list(dict.fromkeys(record.strategy_id for record in result.history))
    assert ran == expected_strategies
