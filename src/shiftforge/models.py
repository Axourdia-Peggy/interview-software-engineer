"""Shared data model for the whole pipeline.

Every stage exchanges these dataclasses; nothing passes raw dicts across a stage
boundary. Keep this module free of I/O so it can be imported from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class ShiftType:
    """A named block of hours within a calendar day."""

    shift_type_id: str
    display_name: str
    start_hour: int
    end_hour: int
    duration_hours: int


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    skills: tuple[str, ...]
    seniority: int
    max_shifts: int

    def can_perform(self, role: str) -> bool:
        return role in self.skills


@dataclass(frozen=True)
class DemandEntry:
    """One row of the demand table: how many people of a role per shift type, per day."""

    shift_type_id: str
    role: str
    headcount: int


@dataclass(frozen=True)
class Slot:
    """A single seat to be filled: one day, one shift type, one role, one seat index."""

    day: date
    shift_type_id: str
    role: str
    seat: int

    @property
    def key(self) -> str:
        return f"{self.day.isoformat()}|{self.shift_type_id}|{self.role}|{self.seat}"


@dataclass(frozen=True)
class Assignment:
    slot: Slot
    employee_id: str


@dataclass
class ScheduleSpec:
    """Parsed and normalised user request."""

    project_name: str
    start_date: date
    days: int
    employees: tuple[Employee, ...]
    demand: tuple[DemandEntry, ...]
    unavailability: frozenset[tuple[str, date]]
    max_iterations: int
    max_strategy_switches: int

    def calendar(self) -> list[date]:
        return [self.start_date + timedelta(days=offset) for offset in range(self.days)]

    def employee_by_id(self, employee_id: str) -> Employee:
        for employee in self.employees:
            if employee.employee_id == employee_id:
                return employee
        raise KeyError(f"unknown employee_id: {employee_id}")

    def is_available(self, employee_id: str, day: date) -> bool:
        return (employee_id, day) not in self.unavailability


@dataclass
class Roster:
    """A candidate schedule produced by a strategy."""

    strategy_id: str
    assignments: list[Assignment] = field(default_factory=list)
    unfilled: list[Slot] = field(default_factory=list)

    def assignments_for(self, employee_id: str) -> list[Assignment]:
        return [a for a in self.assignments if a.employee_id == employee_id]

    def days_worked(self, employee_id: str) -> list[date]:
        return sorted({a.slot.day for a in self.assignments_for(employee_id)})


@dataclass(frozen=True)
class Violation:
    rule_id: str
    rule_name: str
    severity: str
    message: str


@dataclass
class ValidationReport:
    violations: list[Violation] = field(default_factory=list)

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "hard"]

    @property
    def soft_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "soft"]

    @property
    def passed(self) -> bool:
        """A roster is deliverable only when no hard rule is violated."""
        return not self.hard_violations
