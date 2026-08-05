"""Shared orchestration used by every entry point.

Both the CLI and the programmatic API must go through `run_project` so the two
front ends cannot drift apart in behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import CatalogBundle, load_catalogs
from .deliverables import write_package
from .engine import RunResult, run
from .models import ScheduleSpec
from .spec_parser import parse_spec

DEFAULT_OUTPUT_DIR = Path("output")


@dataclass
class ProjectRun:
    spec: ScheduleSpec
    catalogs: CatalogBundle
    result: RunResult
    package_dir: Path | None


def run_project(
    spec_path: Path,
    config_dir: Path | None = None,
    output_dir: Path | None = None,
    write_output: bool = True,
) -> ProjectRun:
    """Parse, solve and (optionally) write the handoff package."""
    catalogs = load_catalogs(config_dir)
    spec = parse_spec(spec_path, catalogs)
    result = run(spec, catalogs)

    package_dir = None
    if write_output:
        package_dir = write_package(spec, catalogs, result, output_dir or DEFAULT_OUTPUT_DIR)

    return ProjectRun(spec=spec, catalogs=catalogs, result=result, package_dir=package_dir)
