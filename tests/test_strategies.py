"""Strategy plugins.

Every strategy build must start from an empty booking ledger. Strategies are
deterministic: slots are visited in a fixed order and ties are broken by
employee_id, so the same spec, strategy and pressure always give the same
roster. A second build that differs from the first can only mean state leaked
in from the earlier build.

No strategy may build a roster that already breaks a hard rule: a seat nobody
can take goes to `unfilled` (reported by R001), never to an ineligible person.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shiftforge.config import ConfigError, load_catalogs
from shiftforge.models import DemandEntry, Employee, Roster, ScheduleSpec, Slot
from shiftforge.spec_parser import expand_slots, parse_spec
from shiftforge.strategies import StrategyContext, load_strategy
from shiftforge.strategies.base import breaks_rest
from shiftforge.validator import validate

from .conftest import EXAMPLES_DIR, rule_params

STRATEGY_IDS = ["balanced_rotation", "seniority_first", "coverage_first"]
EXAMPLES = ["clinic_week", "ward_tight", "pharmacy_relief"]


@pytest.fixture
def ward_tight(catalogs):
    # The example the shared-ledger bug showed up in: it needs more than one build.
    return parse_spec(EXAMPLES_DIR / "ward_tight.json", catalogs)


def _build(catalogs, spec, strategy_id: str, pressure: int = 0) -> Roster:
    definition = next(d for d in catalogs.strategies if d.strategy_id == strategy_id)
    context = StrategyContext(
        spec=spec, catalogs=catalogs, tuning=definition.tuning, pressure=pressure
    )
    return load_strategy(definition).build(expand_slots(spec), context)


def _signature(roster: Roster) -> tuple[list[tuple[str, str]], list[str]]:
    assigned = sorted((a.slot.key, a.employee_id) for a in roster.assignments)
    unfilled = sorted(slot.key for slot in roster.unfilled)
    return assigned, unfilled


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_each_build_gets_a_fresh_ledger(catalogs, ward_tight, strategy_id):
    # Checked directly, because a shared ledger also leaks across tests: once it
    # is saturated every build leaves all seats unfilled, and two such builds
    # compare equal in the behavioural tests below.
    definition = next(d for d in catalogs.strategies if d.strategy_id == strategy_id)
    strategy = load_strategy(definition)
    _build(catalogs, ward_tight, strategy_id)

    ledger = strategy.ledger()
    assert ledger == {}
    assert ledger is not strategy.ledger()
    assert ledger is not load_strategy(definition).ledger()


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_repeated_builds_are_independent(catalogs, ward_tight, strategy_id):
    # Regression: the ledger was a class attribute, so the second build started
    # with every booking of the first one (ward_tight: 1 unfilled seat, then 33).
    first = _build(catalogs, ward_tight, strategy_id)
    second = _build(catalogs, ward_tight, strategy_id)

    assert _signature(second) == _signature(first)


def test_strategies_do_not_share_bookings(catalogs, ward_tight):
    # The ledger was shared across strategy classes too, so switching strategy
    # did not give the next one a clean start.
    alone = _build(catalogs, ward_tight, "seniority_first")

    _build(catalogs, ward_tight, "balanced_rotation")
    after_balanced = _build(catalogs, ward_tight, "seniority_first")

    assert _signature(after_balanced) == _signature(alone)


@pytest.mark.parametrize("example", EXAMPLES)
@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
@pytest.mark.parametrize("pressure", [0, 1, 2, 3])
def test_no_hard_violation_by_construction(catalogs, example, strategy_id, pressure):
    # The spec lets a strategy leave a seat unfilled (reported by R001), but never
    # fill one with somebody who breaks a hard rule. Covers every strategy on every
    # example, including combinations the decision loop never reaches.
    spec = parse_spec(EXAMPLES_DIR / f"{example}.json", catalogs)
    roster = _build(catalogs, spec, strategy_id, pressure)
    report = validate(roster, spec, catalogs)

    not_coverage = [v.message for v in report.hard_violations if v.rule_name != "coverage"]
    assert not_coverage == []
    assert len(report.hard_violations) == len(roster.unfilled)


# --- R004 transitions come from the rule catalog ----------------------------


def _forbid_evening_to_morning(payload):
    # Swap the shipped night -> morning pair for a different one, so a gate that
    # still hard-codes night -> morning gives the opposite answer on both pairs.
    rule_params(payload, "rest_between_shifts")["forbidden_transitions"] = [["evening", "morning"]]


def test_context_reads_rest_transitions_from_the_catalog(edited_configs):
    catalogs = load_catalogs(edited_configs(_forbid_evening_to_morning))
    context = StrategyContext(spec=None, catalogs=catalogs, tuning={})

    assert context.forbidden_transitions() == frozenset({("evening", "morning")})


def test_missing_rest_transitions_raises_config_error(edited_configs):
    def drop_key(payload):
        del rule_params(payload, "rest_between_shifts")["forbidden_transitions"]

    catalogs = load_catalogs(edited_configs(drop_key))
    context = StrategyContext(spec=None, catalogs=catalogs, tuning={})

    with pytest.raises(ConfigError, match="forbidden_transitions"):
        context.forbidden_transitions()


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_gate_follows_catalog_rest_transitions(edited_configs, strategy_id):
    # balanced and seniority use the full gate; coverage goes through RestGate
    # first, so both hard-coded places are exercised.
    catalogs = load_catalogs(edited_configs(_forbid_evening_to_morning))
    definition = next(d for d in catalogs.strategies if d.strategy_id == strategy_id)
    strategy = load_strategy(definition)
    rest = StrategyContext(spec=None, catalogs=catalogs, tuning={}).forbidden_transitions()

    day1 = date(2026, 1, 5)
    day2 = day1 + timedelta(days=1)
    spec = ScheduleSpec(
        project_name="unit",
        start_date=day1,
        days=2,
        employees=(Employee("E1", "Nurse", ("nurse",), seniority=1, max_shifts=7),),
        demand=(),
        unavailability=frozenset(),
        max_iterations=1,
        max_strategy_switches=0,
    )
    morning = Slot(day2, "morning", "nurse", 0)
    taken_days = {"E1": {day1}}

    after_evening = {"E1": {day1: "evening"}}
    after_night = {"E1": {day1: "night"}}
    assert not strategy.eligible("E1", morning, spec, taken_days, after_evening, 5, rest)
    assert strategy.eligible("E1", morning, spec, taken_days, after_night, 5, rest)


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_strategies_respect_a_changed_rest_rule(edited_configs, strategy_id):
    # clinic_week is the only example with both evening and morning shifts.
    catalogs = load_catalogs(edited_configs(_forbid_evening_to_morning))
    spec = parse_spec(EXAMPLES_DIR / "clinic_week.json", catalogs)
    roster = _build(catalogs, spec, strategy_id)
    report = validate(roster, spec, catalogs)

    rest_violations = [v.message for v in report.violations if v.rule_name == "rest_between_shifts"]
    assert rest_violations == []


# --- R004 looks at both neighbouring days -----------------------------------


def test_breaks_rest_checks_both_neighbouring_days():
    forbidden = frozenset({("night", "morning")})
    day1, day2 = date(2026, 1, 5), date(2026, 1, 6)

    # The following day is already booked: the case the gate used to miss.
    next_morning = {"E1": {day2: "morning"}}
    assert breaks_rest("E1", Slot(day1, "night", "nurse", 0), next_morning, forbidden)

    previous_night = {"E1": {day1: "night"}}
    assert breaks_rest("E1", Slot(day2, "morning", "nurse", 0), previous_night, forbidden)
    assert not breaks_rest("E1", Slot(day2, "evening", "nurse", 0), previous_night, forbidden)


def test_coverage_first_respects_rest_when_filling_out_of_date_order(catalogs):
    # Regression: senior (2 people) is scarcer than nurse (3 people), so
    # coverage_first books every morning senior seat before any night nurse
    # seat. S1 and S2 alternate the senior mornings; when N1 runs out, a night
    # seat goes to whoever is lightest, and with a previous-day-only check that
    # was S2 on the night before one of S2's senior mornings.
    spec = ScheduleSpec(
        project_name="out_of_order_rest",
        start_date=date(2026, 3, 5),
        days=7,
        employees=(
            Employee("N1", "Nurse", ("nurse",), seniority=1, max_shifts=7),
            Employee("S1", "Senior 1", ("nurse", "senior"), seniority=5, max_shifts=7),
            Employee("S2", "Senior 2", ("nurse", "senior"), seniority=5, max_shifts=7),
        ),
        demand=(
            DemandEntry("morning", "senior", 1),
            DemandEntry("night", "nurse", 1),
        ),
        unavailability=frozenset(),
        max_iterations=1,
        max_strategy_switches=0,
    )
    roster = _build(catalogs, spec, "coverage_first")
    report = validate(roster, spec, catalogs)

    rest_violations = [v.message for v in report.violations if v.rule_name == "rest_between_shifts"]
    assert rest_violations == []
    # Too few people to fill everything: the gate must leave seats empty instead.
    assert len(report.hard_violations) == len(roster.unfilled)
