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

Commands:

* ``lint``: validate scenario files, and check their agent ids and routes
  against the eval pack they name;
* ``run``: run scenarios on the scripted fake backend and print a JSON
  result. Exits 1 when any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from yarvelle_core.testing.orch_eval.guard import (
    EvalRefusedError,
    ensure_not_ci,
    ensure_opted_in,
)

PROG = "yarvelle-core eval orchestration"
RUN_BACKENDS = ("fake",)
RESULT_SCHEMA_VERSION = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Local-only evaluation of multi-agent, multi-turn orchestration. "
            "Never runs on CI. Requires YARVELLE_EVAL=1."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    lint = sub.add_parser("lint", help="Validate scenario files against their eval pack without running them")
    lint.add_argument("paths", nargs="+", help="Scenario files or directories")
    lint.add_argument("--pack", help="Eval pack directory (default: found next to the scenarios by pack id)")

    run = sub.add_parser("run", help="Run scenarios and check every turn")
    run.add_argument("paths", nargs="+", help="Scenario files or directories")
    run.add_argument("--pack", help="Eval pack directory (default: found next to the scenarios by pack id)")
    run.add_argument("--backend", default="fake", choices=RUN_BACKENDS, help="Model backend (only the free fake for now)")
    run.add_argument("--scenario", action="append", default=[], help="Run only this scenario id (repeatable)")
    run.add_argument("--out", help="Also write the JSON result to this file")
    return parser


def _load(paths: Sequence[str]) -> List[Tuple[Path, Any]]:
    from yarvelle_core.testing.orch_eval.loader import load_scenario_files

    return load_scenario_files(paths)


def _resolve_packs(loaded: Sequence[Tuple[Path, Any]], pack_dir: Optional[str]) -> Tuple[Dict[str, Any], List[str]]:
    """Loads the pack for each scenario. Returns packs by id and the problems found."""
    from yarvelle_core.testing.orch_eval.pack import EvalPackError, find_pack_dir, load_eval_pack

    packs: Dict[str, Any] = {}
    problems: List[str] = []
    if pack_dir is not None:
        try:
            pack = load_eval_pack(pack_dir)
        except EvalPackError as err:
            return {}, [f"Pack error: {err}"]
        packs[pack.id] = pack
        return packs, problems
    for path, scenario in loaded:
        if scenario.pack in packs:
            continue
        found = find_pack_dir(path, scenario.pack)
        if found is None:
            problems.append(f"{path}: pack {scenario.pack!r} not found next to the scenario; pass --pack")
            continue
        try:
            packs[scenario.pack] = load_eval_pack(found)
        except EvalPackError as err:
            problems.append(f"Pack error: {err}")
    return packs, problems


def _lint(loaded: Sequence[Tuple[Path, Any]], packs: Dict[str, Any]) -> List[str]:
    from yarvelle_core.testing.orch_eval.lint import lint_against_pack

    problems: List[str] = []
    for path, scenario in loaded:
        pack = packs.get(scenario.pack)
        if pack is None:
            problems.append(f"{path}: pack {scenario.pack!r} is not loaded")
            continue
        problems.extend(f"{path}: {p}" for p in lint_against_pack(scenario, pack))
    return problems


def _load_and_lint(paths: Sequence[str], pack_dir: Optional[str]) -> Tuple[List[Tuple[Path, Any]], Dict[str, Any], int]:
    from yarvelle_core.testing.orch_eval.loader import ScenarioLoadError

    try:
        loaded = _load(paths)
    except ScenarioLoadError as err:
        print(f"Scenario error: {err}", file=sys.stderr)
        return [], {}, 1
    if not loaded:
        print("No scenario files found.", file=sys.stderr)
        return [], {}, 1
    packs, problems = _resolve_packs(loaded, pack_dir)
    if not problems:
        problems = _lint(loaded, packs)
    for problem in problems:
        print(problem, file=sys.stderr)
    return loaded, packs, 1 if problems else 0


def _run_lint(paths: Sequence[str], pack_dir: Optional[str] = None) -> int:
    loaded, _packs, code = _load_and_lint(paths, pack_dir)
    if code:
        return code
    for _path, scenario in loaded:
        print(f"ok  {scenario.id}  ({len(scenario.turns)} turns)")
    print(f"{len(loaded)} scenario(s) valid.")
    return 0


def _backend_factory(name: str) -> Any:
    if name == "fake":
        from yarvelle_core.testing.orch_eval.fake import FakeBackend

        return FakeBackend
    raise ValueError(f"backend {name!r} is not available")


def run_result(results: Sequence[Any], backend: Any) -> Dict[str, Any]:
    """The JSON document ``run`` prints."""
    passed = sum(1 for r in results if r.passed)
    return {
        "schema": RESULT_SCHEMA_VERSION,
        "backend": backend.describe(),
        "passed": passed == len(results),
        "totals": {"scenarios": len(results), "passed": passed, "failed": len(results) - passed},
        "scenarios": [r.to_dict() for r in results],
    }


def _run(args: argparse.Namespace) -> int:
    from yarvelle_core.testing.orch_eval.driver import run_scenarios

    loaded, packs, code = _load_and_lint(args.paths, args.pack)
    if code:
        return code
    wanted = set(args.scenario)
    selected = [(p, s) for p, s in loaded if not wanted or s.id in wanted]
    unknown = sorted(wanted - {s.id for _p, s in loaded})
    if unknown:
        print(f"Unknown scenario id(s): {unknown}", file=sys.stderr)
        return 1
    factory = _backend_factory(args.backend)
    results: List[Any] = []
    for pack_id in sorted({s.pack for _p, s in selected}):
        group = [s for _p, s in selected if s.pack == pack_id]
        results.extend(asyncio.run(run_scenarios(group, packs[pack_id], factory)))
    if not results:
        print(f"No scenario lists the {args.backend!r} backend.", file=sys.stderr)
        return 1
    document = run_result(results, factory())
    text = json.dumps(document, indent=2, sort_keys=False, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    for r in results:
        mark = "pass" if r.passed else "FAIL"
        print(f"{mark}  {r.scenario_id}", file=sys.stderr)
        for failure in r.failures():
            print(f"      {failure}", file=sys.stderr)
    totals = document["totals"]
    print(f"{totals['passed']} of {totals['scenarios']} scenario(s) passed.", file=sys.stderr)
    return 0 if document["passed"] else 1


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
        return _run_lint(args.paths, args.pack)
    if args.command == "run":
        return _run(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
