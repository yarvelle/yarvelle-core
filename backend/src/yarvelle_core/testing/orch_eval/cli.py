# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Command line for the orchestration eval harness.

Available as ``yarvelle-core eval orchestration ...`` and
``python -m yarvelle_core.testing.orch_eval ...``. The CI check runs before
anything else, including argument parsing, and exits 3. Every command then
needs ``YARVELLE_EVAL=1``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from yarvelle_core.testing.orch_eval.guard import (
    EvalRefusedError,
    ensure_not_ci,
    ensure_opted_in,
)

PROG = "yarvelle-core eval orchestration"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Local-only evaluation of multi-agent, multi-turn orchestration. "
            "Never runs on CI. Requires YARVELLE_EVAL=1."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    lint = sub.add_parser("lint", help="Validate scenario files without running them")
    lint.add_argument("paths", nargs="+", help="Scenario files or directories")
    return parser


def _run_lint(paths: Sequence[str]) -> int:
    from yarvelle_core.testing.orch_eval.loader import ScenarioLoadError, load_scenarios

    try:
        scenarios = load_scenarios(paths)
    except ScenarioLoadError as err:
        print(f"Scenario error: {err}", file=sys.stderr)
        return 1
    if not scenarios:
        print("No scenario files found.", file=sys.stderr)
        return 1
    for scenario in scenarios:
        print(f"ok  {scenario.id}  ({len(scenario.turns)} turns)")
    print(f"{len(scenarios)} scenario(s) valid.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        ensure_not_ci()
    except EvalRefusedError as err:
        print(str(err), file=sys.stderr)
        return err.exit_code

    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if args.command is None:
        parser.print_help()
        return 0

    try:
        ensure_opted_in()
    except EvalRefusedError as err:
        print(str(err), file=sys.stderr)
        return err.exit_code

    if args.command == "lint":
        return _run_lint(args.paths)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
