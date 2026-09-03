"""Stage 4 - Rule validation.

Every rule in configs/rule_catalog.json is checked here. A rule the catalog
declares but this module cannot evaluate is an error, not a silent skip: an
unevaluated rule would let a non-conformant roster reach the handoff package.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from .config import CatalogBundle, RuleDef
from .models import Roster, ScheduleSpec, ValidationReport, Violation
from .spec_parser import expand_slots


def _check_coverage(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    required = {slot.key for slot in expand_slots(spec)}
    filled = {a.slot.key for a in roster.assignments}

    violations = []
    for missing in sorted(required - filled):
        violations.append(
            Violation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                message=f"slot not covered: {missing}",
            )
        )

    seen: dict[str, int] = {}
    for assignment in roster.assignments:
        seen[assignment.slot.key] = seen.get(assignment.slot.key, 0) + 1
    for key, count in sorted(seen.items()):
        if count > 1:
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"slot assigned {count} times: {key}",
                )
            )
    return violations


def _check_qualification(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    violations = []
    for assignment in roster.assignments:
        employee = spec.employee_by_id(assignment.employee_id)
        if not employee.can_perform(assignment.slot.role):
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=(
                        f"{employee.employee_id} lacks role {assignment.slot.role!r} "
                        f"for {assignment.slot.key}"
                    ),
                )
            )
    return violations


def _check_no_double_booking(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    per_employee_day: dict[tuple[str, date], int] = {}
    for assignment in roster.assignments:
        key = (assignment.employee_id, assignment.slot.day)
        per_employee_day[key] = per_employee_day.get(key, 0) + 1

    violations = []
    for (employee_id, day), count in sorted(per_employee_day.items()):
        if count > 1:
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"{employee_id} has {count} assignments on {day.isoformat()}",
                )
            )
    return violations


def _check_rest_between_shifts(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    forbidden = {tuple(pair) for pair in rule.params.get("forbidden_transitions", [])}

    by_employee: dict[str, dict[date, str]] = {}
    for assignment in roster.assignments:
        by_employee.setdefault(assignment.employee_id, {})[assignment.slot.day] = (
            assignment.slot.shift_type_id
        )

    violations = []
    for employee_id, day_map in sorted(by_employee.items()):
        for day, shift_type_id in sorted(day_map.items()):
            next_shift = day_map.get(day + timedelta(days=1))
            if next_shift and (shift_type_id, next_shift) in forbidden:
                violations.append(
                    Violation(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        message=(
                            f"{employee_id} works {shift_type_id} on {day.isoformat()} "
                            f"then {next_shift} the next day"
                        ),
                    )
                )
    return violations


def _check_max_consecutive_days(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    max_days = rule.params.get("max_days", 5)

    violations = []
    for employee in spec.employees:
        days = roster.days_worked(employee.employee_id)
        if not days:
            continue

        run = 1
        longest = 1
        for previous, current in zip(days, days[1:], strict=False):
            if current - previous == timedelta(days=1):
                run += 1
                longest = max(longest, run)
            else:
                run = 1

        if longest > max_days:
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=(
                        f"{employee.employee_id} works {longest} consecutive days "
                        f"(limit {max_days})"
                    ),
                )
            )
    return violations


def _check_weekly_hours(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    min_hours = rule.params.get("min_hours", 0)
    max_hours = rule.params.get("max_hours", 24 * 7)

    violations = []
    for employee in spec.employees:
        hours = 0
        for assignment in roster.assignments_for(employee.employee_id):
            hours += catalogs.shift_type(assignment.slot.shift_type_id).duration_hours

        if hours < min_hours or hours > max_hours:
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=(
                        f"{employee.employee_id} is scheduled {hours}h, "
                        f"outside [{min_hours}, {max_hours}]"
                    ),
                )
            )
    return violations


def _check_fairness(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    max_spread = rule.params.get("max_spread", 3)

    counts = [len(roster.assignments_for(e.employee_id)) for e in spec.employees]
    if not counts:
        return []

    spread = max(counts) - min(counts)
    if spread > max_spread:
        return [
            Violation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                message=f"shift count spread is {spread} (limit {max_spread})",
            )
        ]
    return []


def _check_night_shift_quota(
    roster: Roster, spec: ScheduleSpec, rule: RuleDef, catalogs: CatalogBundle
) -> list[Violation]:
    max_nights = rule.params.get("max_nights", 2)

    violations = []
    for employee in spec.employees:
        nights = sum(
            1
            for a in roster.assignments_for(employee.employee_id)
            if a.slot.shift_type_id == "night"
        )
        if nights > max_nights:
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=(
                        f"{employee.employee_id} is assigned {nights} night shifts "
                        f"(limit {max_nights})"
                    ),
                )
            )
    return violations


CheckFn = Callable[[Roster, ScheduleSpec, RuleDef, CatalogBundle], list[Violation]]

CHECKS: dict[str, CheckFn] = {
    "coverage": _check_coverage,
    "qualification": _check_qualification,
    "no_double_booking": _check_no_double_booking,
    "rest_between_shifts": _check_rest_between_shifts,
    "max_consecutive_days": _check_max_consecutive_days,
    "weekly_hours": _check_weekly_hours,
    "fairness": _check_fairness,
    "night_shift_quota": _check_night_shift_quota,
}


class RuleCoverageError(RuntimeError):
    """Raised when the catalog declares a rule this build cannot evaluate."""


def validate(roster: Roster, spec: ScheduleSpec, catalogs: CatalogBundle) -> ValidationReport:
    """Run every catalog rule against the roster."""
    report = ValidationReport()

    for rule in catalogs.rules:
        check = CHECKS.get(rule.name)
        if check is None:
            raise RuleCoverageError(
                f"rule {rule.rule_id} ({rule.name!r}) is declared in the catalog "
                f"but has no implementation in validator.CHECKS"
            )
        report.violations.extend(check(roster, spec, rule, catalogs))

    return report
