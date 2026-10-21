"""Rule parameters must come from the rule catalog, and a missing one must fail loudly."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shiftforge.cli import main
from shiftforge.config import ConfigError, load_catalogs
from shiftforge.models import Assignment, Employee, Roster, ScheduleSpec, Slot
from shiftforge.validator import validate

from .conftest import EXAMPLES_DIR, rule_params

START = date(2026, 1, 5)
NURSE = Employee("E1", "Nurse", ("nurse",), seniority=1, max_shifts=7)


def _spec() -> ScheduleSpec:
    return ScheduleSpec(
        project_name="unit",
        start_date=START,
        days=7,
        employees=(NURSE,),
        demand=(),  # no demand, so R001 stays quiet
        unavailability=frozenset(),
        max_iterations=1,
        max_strategy_switches=0,
    )


def _two_morning_shifts() -> Roster:
    """E1 works two 8h shifts: 16h, below the catalog's 24h floor."""
    roster = Roster(strategy_id="hand_made")
    for offset in range(2):
        slot = Slot(START + timedelta(days=offset), "morning", "nurse", 0)
        roster.assignments.append(Assignment(slot=slot, employee_id="E1"))
    return roster


def _weekly_hours(report):
    return [v for v in report.violations if v.rule_name == "weekly_hours"]


# --- R006 reads the catalog's key names -----------------------------------


def test_weekly_hours_uses_catalog_bounds(catalogs):
    # Regression: the check read 'min_hours'/'max_hours' while the catalog declares
    # 'min_weekly_hours'/'max_weekly_hours', so it fell back to 0..168 and never fired.
    report = validate(_two_morning_shifts(), _spec(), catalogs)

    violations = _weekly_hours(report)
    assert [v.message for v in violations] == ["E1 is scheduled 16h, outside [24, 40]"]
    assert violations[0].severity == "soft"


def test_weekly_hours_follows_a_catalog_change(edited_configs):
    def lower_the_floor(payload):
        rule_params(payload, "weekly_hours")["min_weekly_hours"] = 16

    catalogs = load_catalogs(edited_configs(lower_the_floor))
    report = validate(_two_morning_shifts(), _spec(), catalogs)

    assert _weekly_hours(report) == []


# --- a missing parameter stops the run --------------------------------------

PARAMS = [
    ("rest_between_shifts", "forbidden_transitions"),
    ("max_consecutive_days", "max_days"),
    ("weekly_hours", "min_weekly_hours"),
    ("weekly_hours", "max_weekly_hours"),
    ("fairness", "max_spread"),
    ("night_shift_quota", "max_nights"),
]


@pytest.mark.parametrize(("rule_name", "key"), PARAMS)
def test_missing_param_raises_config_error(edited_configs, rule_name, key):
    def drop_key(payload):
        del rule_params(payload, rule_name)[key]

    catalogs = load_catalogs(edited_configs(drop_key))
    with pytest.raises(ConfigError, match=key):
        validate(Roster(strategy_id="empty"), _spec(), catalogs)


def test_missing_param_exits_with_bad_input(edited_configs, capsys):
    def rename_key(payload):
        params = rule_params(payload, "max_consecutive_days")
        params["max_daysX"] = params.pop("max_days")

    config_dir = edited_configs(rename_key)
    exit_code = main(
        [str(EXAMPLES_DIR / "clinic_week.json"), "--config-dir", str(config_dir), "--dry-run"]
    )

    assert exit_code == 2
    assert "missing required param 'max_days'" in capsys.readouterr().err
