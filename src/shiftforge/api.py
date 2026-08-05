"""Programmatic entry point.

The second front end alongside the CLI. Both are thin wrappers over
runner.run_project; anything either one decides on its own is a place the two
can drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runner import DEFAULT_OUTPUT_DIR, run_project


def generate_schedule(
    spec_path: str | Path,
    config_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    write_output: bool = True,
) -> dict[str, Any]:
    """Run one project and return a JSON-serialisable summary.

    The returned dict is the API's contract: the same keys the CLI prints, so a
    caller can compare the two front ends field by field.
    """
    project = run_project(
        spec_path=Path(spec_path),
        config_dir=Path(config_dir) if config_dir else None,
        output_dir=Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR,
        write_output=write_output,
    )

    result = project.result
    report = result.report

    return {
        "project_name": project.spec.project_name,
        "converged": result.converged,
        "strategies_tried": list(result.strategies_tried),
        "iterations": result.iterations,
        "hard_violations": len(report.hard_violations) if report else 0,
        "soft_violations": len(report.soft_violations) if report else 0,
        "assignment_count": len(result.roster.assignments) if result.roster else 0,
        "package_dir": str(project.package_dir) if project.package_dir else None,
    }
