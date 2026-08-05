"""Stage 1 - Specification parsing and validation.

Turns the user-supplied request JSON into a ScheduleSpec, rejecting anything the
downstream stages could not act on. Fail fast here rather than producing a
half-valid spec that breaks deeper in the pipeline.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import SUPPORTED_SCHEMA_VERSION, CatalogBundle
from .models import DemandEntry, Employee, ScheduleSpec


class SpecError(ValueError):
    """Raised when the request document cannot be turned into a usable spec."""


def _parse_date(raw: str, field_name: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{field_name} must be an ISO date (YYYY-MM-DD), got {raw!r}") from exc


def _require(payload: dict[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise SpecError(f"{context} is missing required field {key!r}")
    return payload[key]


def parse_spec(path: Path, catalogs: CatalogBundle) -> ScheduleSpec:
    """Read a request document and validate it against the loaded catalogs."""
    if not path.is_file():
        raise SpecError(f"spec file not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec file is not valid JSON: {path}: {exc}") from exc

    version = payload.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise SpecError(
            f"spec declares schema_version {version!r}, "
            f"this build supports {SUPPORTED_SCHEMA_VERSION!r}"
        )

    project_name = _require(payload, "project_name", "spec")

    horizon = _require(payload, "planning_horizon", "spec")
    start_date = _parse_date(_require(horizon, "start_date", "planning_horizon"), "start_date")
    days = _require(horizon, "days", "planning_horizon")
    if not isinstance(days, int) or days < 1:
        raise SpecError(f"planning_horizon.days must be a positive integer, got {days!r}")

    employees: list[Employee] = []
    seen_ids: set[str] = set()
    for entry in _require(payload, "employees", "spec"):
        employee_id = _require(entry, "employee_id", "employee")
        if employee_id in seen_ids:
            raise SpecError(f"duplicate employee_id: {employee_id}")
        seen_ids.add(employee_id)
        employees.append(
            Employee(
                employee_id=employee_id,
                name=_require(entry, "name", f"employee {employee_id}"),
                skills=tuple(_require(entry, "skills", f"employee {employee_id}")),
                seniority=entry.get("seniority", 0),
                max_shifts=entry.get("max_shifts", days),
            )
        )
    if not employees:
        raise SpecError("spec declares no employees")

    demand: list[DemandEntry] = []
    for entry in _require(payload, "demand", "spec"):
        shift_type_id = _require(entry, "shift_type_id", "demand row")
        # Referential integrity: demand may only cite shift types the catalog knows.
        catalogs.shift_type(shift_type_id)
        headcount = _require(entry, "headcount", "demand row")
        if not isinstance(headcount, int) or headcount < 1:
            raise SpecError(f"demand.headcount must be a positive integer, got {headcount!r}")
        demand.append(
            DemandEntry(
                shift_type_id=shift_type_id,
                role=_require(entry, "role", "demand row"),
                headcount=headcount,
            )
        )
    if not demand:
        raise SpecError("spec declares no demand")

    unavailability: set[tuple[str, date]] = set()
    for entry in payload.get("unavailability", []):
        employee_id = _require(entry, "employee_id", "unavailability row")
        if employee_id not in seen_ids:
            raise SpecError(f"unavailability cites unknown employee_id: {employee_id}")
        unavailability.add(
            (employee_id, _parse_date(_require(entry, "date", "unavailability row"), "date"))
        )

    convergence = payload.get("convergence", {})
    max_iterations = convergence.get("max_iterations", 10)
    max_strategy_switches = convergence.get("max_strategy_switches", 2)

    return ScheduleSpec(
        project_name=project_name,
        start_date=start_date,
        days=days,
        employees=tuple(employees),
        demand=tuple(demand),
        unavailability=frozenset(unavailability),
        max_iterations=max_iterations,
        max_strategy_switches=max_strategy_switches,
    )


def expand_slots(spec: ScheduleSpec) -> list:
    """Cross the demand table with the calendar to produce every seat to fill."""
    from .models import Slot

    slots: list[Slot] = []
    for day in spec.calendar():
        for entry in spec.demand:
            for seat in range(entry.headcount):
                slots.append(
                    Slot(day=day, shift_type_id=entry.shift_type_id, role=entry.role, seat=seat)
                )
    return slots
