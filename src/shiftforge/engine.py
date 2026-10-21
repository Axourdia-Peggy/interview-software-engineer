"""Stage 2/3/5 - Strategy selection, generation, and the convergence decision loop.

The loop is the core of the module:

    [pass]                  -> deliver
    [fail, same strategy]   -> raise pressure and retry the same strategy
    [fail, exhausted]       -> switch to the next strategy in the catalog

"Exhausted" means the current strategy has consumed its retry budget, or the
report shows a defect that more pressure cannot fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import CatalogBundle, ConfigError, StrategyDef
from .models import Roster, ScheduleSpec, ValidationReport
from .spec_parser import expand_slots
from .strategies import StrategyContext, load_strategy
from .validator import validate


@dataclass
class IterationRecord:
    iteration: int
    strategy_id: str
    pressure: int
    hard_violations: int
    soft_violations: int
    unfilled: int
    decision: str


@dataclass
class RunResult:
    converged: bool
    roster: Roster | None
    report: ValidationReport | None
    history: list[IterationRecord] = field(default_factory=list)
    strategies_tried: list[str] = field(default_factory=list)

    @property
    def iterations(self) -> int:
        return len(self.history)


def select_strategies(spec: ScheduleSpec, catalogs: CatalogBundle) -> list[StrategyDef]:
    """Stage 2 - filter the catalog down to strategies applicable to this spec.

    Entries are already sorted by priority when the catalog is loaded, so the
    first survivor is the preferred one.
    """
    applicable: list[StrategyDef] = []

    for definition in catalogs.strategies:
        rules = definition.selection_rules

        max_employees = rules.get("max_employees")
        if max_employees is not None and len(spec.employees) > max_employees:
            continue

        required_roles = set(rules.get("requires_roles", []))
        if required_roles:
            offered = {entry.role for entry in spec.demand}
            if not required_roles.issubset(offered):
                continue

        applicable.append(definition)

    if not applicable:
        raise ConfigError(
            "no strategy in the catalog is applicable to this spec "
            f"({len(spec.employees)} employees)"
        )
    return applicable


def _retry_budget(spec: ScheduleSpec, strategy_count: int) -> int:
    """How many attempts each strategy gets before the loop moves on."""
    if strategy_count < 1:
        return 1
    return max(1, spec.max_iterations // strategy_count)


def run(spec: ScheduleSpec, catalogs: CatalogBundle) -> RunResult:
    """Execute the full generate -> validate -> decide loop."""
    slots = expand_slots(spec)
    candidates = select_strategies(spec, catalogs)

    result = RunResult(converged=False, roster=None, report=None)

    budget = _retry_budget(spec, len(candidates))
    iteration = 0

    best_roster: Roster | None = None
    best_report: ValidationReport | None = None
    best_score: tuple[int, int] | None = None

    # `switches` counts how many times the loop has moved on to another strategy:
    # 0 for the first candidate. N allowed switches means up to N + 1 strategies.
    for switches, definition in enumerate(candidates):
        if switches > spec.max_strategy_switches:
            break

        result.strategies_tried.append(definition.strategy_id)
        strategy = load_strategy(definition)

        # Attempt index doubles as the pressure level for this strategy.
        for pressure in range(budget):
            if iteration >= spec.max_iterations:
                break
            iteration += 1

            context = StrategyContext(
                spec=spec,
                catalogs=catalogs,
                tuning=definition.tuning,
                pressure=pressure,
            )
            roster = strategy.build(slots, context)
            report = validate(roster, spec, catalogs)

            score = (len(report.hard_violations), len(report.soft_violations))
            if best_score is None or score < best_score:
                best_roster, best_report, best_score = roster, report, score

            if report.passed:
                result.history.append(
                    IterationRecord(
                        iteration=iteration,
                        strategy_id=definition.strategy_id,
                        pressure=pressure,
                        hard_violations=0,
                        soft_violations=len(report.soft_violations),
                        unfilled=len(roster.unfilled),
                        decision="deliver",
                    )
                )
                result.converged = True
                result.roster = roster
                result.report = report
                return result

            # Not converged. Decide between another attempt here and a switch.
            exhausted = pressure == budget - 1 or not _pressure_can_help(report)
            decision = "switch_strategy" if exhausted else "raise_pressure"

            result.history.append(
                IterationRecord(
                    iteration=iteration,
                    strategy_id=definition.strategy_id,
                    pressure=pressure,
                    hard_violations=len(report.hard_violations),
                    soft_violations=len(report.soft_violations),
                    unfilled=len(roster.unfilled),
                    decision=decision,
                )
            )

            if decision == "switch_strategy":
                break

    result.roster = best_roster
    result.report = best_report
    return result


def _pressure_can_help(report: ValidationReport) -> bool:
    """Whether retrying the same strategy under more pressure is worth an attempt.

    Pressure only relaxes a strategy's own preference ordering. It cannot create
    a qualified employee out of nothing, so a qualification defect means the
    current strategy is at its limit.
    """
    return all(v.rule_name != "qualification" for v in report.hard_violations)
