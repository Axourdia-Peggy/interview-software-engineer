"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError
from .runner import DEFAULT_OUTPUT_DIR, run_project
from .spec_parser import SpecError
from .validator import RuleCoverageError

EXIT_OK = 0
EXIT_NOT_CONVERGED = 1
EXIT_BAD_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shiftforge",
        description="Generate a shift roster from a request specification.",
    )
    parser.add_argument("spec", type=Path, help="path to the request JSON")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="directory holding the three catalogs (default: repo configs/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"where to write the handoff package (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the loop but do not write any files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the decision taken at every iteration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        project = run_project(
            spec_path=args.spec,
            config_dir=args.config_dir,
            output_dir=args.output_dir,
            write_output=not args.dry_run,
        )
    except (SpecError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except RuleCoverageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    result = project.result

    if args.verbose:
        for record in result.history:
            print(
                f"  iter {record.iteration:>2} "
                f"strategy={record.strategy_id} "
                f"pressure={record.pressure} "
                f"hard={record.hard_violations} "
                f"soft={record.soft_violations} "
                f"unfilled={record.unfilled} "
                f"-> {record.decision}"
            )

    print(f"project        : {project.spec.project_name}")
    print(f"strategies     : {', '.join(result.strategies_tried) or '(none)'}")
    print(f"iterations     : {result.iterations}")
    print(f"converged      : {result.converged}")

    if result.report is not None:
        print(f"hard violations: {len(result.report.hard_violations)}")
        print(f"soft violations: {len(result.report.soft_violations)}")

    if project.package_dir is not None:
        print(f"package        : {project.package_dir}")

    if not result.converged:
        print("did not converge - see validation.txt for the blocking rules", file=sys.stderr)
        return EXIT_NOT_CONVERGED

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
