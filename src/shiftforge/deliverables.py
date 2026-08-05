"""Stage 6 - Handoff package generation.

Writes the deliverable set described in the module specification:

    <output_dir>/<project_name>/
        roster.csv          one row per assignment
        roster.json         structured roster for downstream tools
        validation.txt      rule-by-rule verdict
        run_summary.json    machine-readable record of the decision loop
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import CatalogBundle
from .engine import RunResult
from .models import ScheduleSpec

ROSTER_CSV_HEADER = ["date", "shift_type", "role", "seat", "employee_id", "employee_name"]


def write_package(
    spec: ScheduleSpec,
    catalogs: CatalogBundle,
    result: RunResult,
    output_dir: Path,
) -> Path:
    """Write the full handoff package and return the project directory."""
    project_dir = output_dir / spec.project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    _write_roster_csv(spec, result, project_dir / "roster.csv")
    _write_roster_json(spec, catalogs, result, project_dir / "roster.json")
    _write_validation(result, project_dir / "validation.txt")
    _write_summary(spec, result, project_dir / "run_summary.json")

    return project_dir


def _write_roster_csv(spec: ScheduleSpec, result: RunResult, path: Path) -> None:
    rows = []
    if result.roster:
        for assignment in sorted(
            result.roster.assignments,
            key=lambda a: (a.slot.day, a.slot.shift_type_id, a.slot.role, a.slot.seat),
        ):
            employee = spec.employee_by_id(assignment.employee_id)
            rows.append(
                [
                    assignment.slot.day.isoformat(),
                    assignment.slot.shift_type_id,
                    assignment.slot.role,
                    assignment.slot.seat,
                    employee.employee_id,
                    employee.name,
                ]
            )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(ROSTER_CSV_HEADER)
        writer.writerows(rows)


def _write_roster_json(
    spec: ScheduleSpec, catalogs: CatalogBundle, result: RunResult, path: Path
) -> None:
    assignments = []
    hours: dict[str, int] = {e.employee_id: 0 for e in spec.employees}

    if result.roster:
        for assignment in sorted(
            result.roster.assignments,
            key=lambda a: (a.slot.day, a.slot.shift_type_id, a.slot.role, a.slot.seat),
        ):
            duration = catalogs.shift_type(assignment.slot.shift_type_id).duration_hours
            hours[assignment.employee_id] += duration
            assignments.append(
                {
                    "date": assignment.slot.day.isoformat(),
                    "shift_type_id": assignment.slot.shift_type_id,
                    "role": assignment.slot.role,
                    "seat": assignment.slot.seat,
                    "employee_id": assignment.employee_id,
                    "hours": duration,
                }
            )

    payload = {
        "project_name": spec.project_name,
        "converged": result.converged,
        "strategy_id": result.roster.strategy_id if result.roster else None,
        "assignments": assignments,
        "hours_per_employee": hours,
        "unfilled": [slot.key for slot in (result.roster.unfilled if result.roster else [])],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _write_validation(result: RunResult, path: Path) -> None:
    lines: list[str] = []
    report = result.report

    if report is None:
        lines.append("NO REPORT - the loop produced no candidate roster.")
    else:
        verdict = "PASS" if report.passed else "FAIL"
        lines.append(f"verdict: {verdict}")
        lines.append(f"hard violations: {len(report.hard_violations)}")
        lines.append(f"soft violations: {len(report.soft_violations)}")
        lines.append("")

        if not report.violations:
            lines.append("no violations recorded.")
        for violation in report.violations:
            lines.append(
                f"[{violation.severity.upper()}] {violation.rule_id} "
                f"{violation.rule_name}: {violation.message}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary(spec: ScheduleSpec, result: RunResult, path: Path) -> None:
    payload = {
        "project_name": spec.project_name,
        "converged": result.converged,
        "iterations": result.iterations,
        "strategies_tried": result.strategies_tried,
        "history": [
            {
                "iteration": record.iteration,
                "strategy_id": record.strategy_id,
                "pressure": record.pressure,
                "hard_violations": record.hard_violations,
                "soft_violations": record.soft_violations,
                "unfilled": record.unfilled,
                "decision": record.decision,
            }
            for record in result.history
        ],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
