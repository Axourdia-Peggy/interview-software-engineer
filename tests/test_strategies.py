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

import pytest

from shiftforge.models import Roster
from shiftforge.spec_parser import expand_slots, parse_spec
from shiftforge.strategies import StrategyContext, load_strategy
from shiftforge.validator import validate

from .conftest import EXAMPLES_DIR

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
