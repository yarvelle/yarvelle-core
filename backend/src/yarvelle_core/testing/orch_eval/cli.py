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
* ``run``: run scenarios on a chosen backend, print JSON, and write
  ``results.json`` / ``report.md`` / ``report.html`` under
  ``~/.yarvelle-evals/<run>/`` (override with ``--out-dir``). Free
  backends: ``fake``, ``replay``, ``ollama``. Paid ``provider`` requires
  ``--max-usd`` greater than 0. Use ``--record`` with ollama/provider to
  write cassettes, or ``--backend replay`` to play them back with no model
  calls. Exits 1 when any check fails, 2 on a baseline regression;
* ``baseline save``: remember a run as the baseline for its backend+model;
* ``compare``: diff a run against a baseline without re-running scenarios.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from yarvelle_core.testing.orch_eval.guard import (
    EvalRefusedError,
    ensure_not_ci,
    ensure_opted_in,
)

PROG = "yarvelle-core eval orchestration"
RUN_BACKENDS = ("fake", "replay", "ollama", "provider")
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
    run.add_argument(
        "--backend",
        default="fake",
        choices=RUN_BACKENDS,
        help="Model backend: fake, replay (cassettes), ollama (free local), provider (paid, needs --max-usd)",
    )
    run.add_argument("--scenario", action="append", default=[], help="Run only this scenario id (repeatable)")
    run.add_argument("--samples", type=int, default=None, help="Override samples per scenario for this backend")
    run.add_argument(
        "--max-usd",
        type=float,
        default=0.0,
        help="Spend ceiling in US dollars for paid backends (default 0 refuses provider runs)",
    )
    run.add_argument("--estimate", action="store_true", help="Print a spend estimate and exit without calling a model")
    run.add_argument("--model", help="Subject model override (Ollama tag or provider model id)")
    run.add_argument("--judge-model", help="Judge model override (must differ from the subject for judged runs)")
    run.add_argument("--provider", default=None, help="Paid provider id (openai, anthropic, google, custom)")
    run.add_argument("--key-file", help="Path to a provider API key file (read only at run time; never logged)")
    run.add_argument("--base-url", help="Override the model endpoint (Ollama or OpenAI-compatible)")
    run.add_argument("--seed", type=int, default=None, help="Sampling seed (default 1729)")
    run.add_argument("--out", help="Also write the JSON result to this file")
    run.add_argument(
        "--out-dir",
        help="Root directory for run reports (default: ~/.yarvelle-evals or YARVELLE_EVALS_DIR)",
    )
    run.add_argument(
        "--baseline",
        help="Compare this run to a baseline (path, run id, or latest:<backend>:<model>)",
    )
    run.add_argument(
        "--save-baseline",
        action="store_true",
        help="After a green run, save it as the baseline for this backend+model",
    )
    run.add_argument(
        "--record",
        action="store_true",
        help="Record live model exchanges to cassettes (ollama or provider only)",
    )
    run.add_argument(
        "--cassette",
        help="Cassette root directory (default: committed cassettes, or YARVELLE_CASSETTES_DIR)",
    )
    run.add_argument(
        "--check-latency",
        action="store_true",
        help="Apply the p95 latency +25%% regression rule even on free backends",
    )
    run.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing the report directory (still prints JSON to stdout)",
    )

    baseline = sub.add_parser("baseline", help="Manage saved baselines under the evals output root")
    baseline_sub = baseline.add_subparsers(dest="baseline_command")
    b_save = baseline_sub.add_parser("save", help="Save a run's results.json as the baseline for its backend+model")
    b_save.add_argument("run", help="Run id, run directory, or path to results.json")
    b_save.add_argument("--out-dir", help="Evals root (default: ~/.yarvelle-evals)")

    compare = sub.add_parser("compare", help="Compare a run against a baseline without re-running")
    compare.add_argument("current", help="Current run id, directory, or results.json")
    compare.add_argument("--baseline", required=True, help="Baseline path, run id, or latest:<backend>:<model>")
    compare.add_argument("--out-dir", help="Evals root used to resolve run ids (default: ~/.yarvelle-evals)")
    compare.add_argument(
        "--check-latency",
        action="store_true",
        help="Apply the p95 latency +25%% regression rule even on free backends",
    )
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


def _cassette_root(args: argparse.Namespace) -> Path:
    from yarvelle_core.testing.orch_eval.cassette import default_cassette_root

    if getattr(args, "cassette", None):
        return Path(args.cassette).expanduser()
    return default_cassette_root()


def _wrap_recording(inner_factory: Any, args: argparse.Namespace, *, backend_label: str, model_label: str) -> Any:
    """Optionally wrap a live backend so every model call is written to a cassette."""
    if not getattr(args, "record", False):
        return inner_factory
    from yarvelle_core.testing.orch_eval.cassette import CassetteBackend

    root = _cassette_root(args)

    def factory() -> Any:
        return CassetteBackend(
            cassette_root=root,
            mode="record",
            inner=inner_factory() if callable(inner_factory) else inner_factory,
            backend_label=backend_label,
            model_label=model_label,
        )

    return factory


def _backend_factory(name: str, args: argparse.Namespace) -> Any:
    """Returns a zero-arg factory that builds one backend instance per scenario."""
    if name == "fake":
        from yarvelle_core.testing.orch_eval.fake import FakeBackend

        return _wrap_recording(FakeBackend, args, backend_label="fake", model_label="scripted")
    if name == "ollama":
        from yarvelle_core.testing.orch_eval.defaults import (
            DEFAULT_OLLAMA_BASE_URL,
            DEFAULT_OLLAMA_JUDGE_MODEL,
            DEFAULT_OLLAMA_SUBJECT_MODEL,
            DEFAULT_SEED,
        )
        from yarvelle_core.testing.orch_eval.ollama_backend import OllamaBackend

        subject = args.model or DEFAULT_OLLAMA_SUBJECT_MODEL
        judge = args.judge_model or DEFAULT_OLLAMA_JUDGE_MODEL
        base = args.base_url or DEFAULT_OLLAMA_BASE_URL
        seed = DEFAULT_SEED if args.seed is None else args.seed

        def factory() -> Any:
            return OllamaBackend(
                subject_model=subject,
                judge_model=judge,
                base_url=base,
                seed=seed,
                require_ready=True,
            )

        return _wrap_recording(factory, args, backend_label="ollama", model_label=subject)
    if name == "provider":
        from yarvelle_core.testing.orch_eval.defaults import (
            DEFAULT_PROVIDER,
            DEFAULT_PROVIDER_JUDGE_MODEL,
            DEFAULT_PROVIDER_SUBJECT_MODEL,
            DEFAULT_SEED,
        )
        from yarvelle_core.testing.orch_eval.provider_backend import ProviderBackend

        subject = args.model or DEFAULT_PROVIDER_SUBJECT_MODEL
        judge = args.judge_model or DEFAULT_PROVIDER_JUDGE_MODEL
        provider = args.provider or DEFAULT_PROVIDER
        seed = DEFAULT_SEED if args.seed is None else args.seed
        max_usd = args.max_usd

        def factory() -> Any:
            return ProviderBackend(
                max_usd=max_usd,
                provider=provider,
                subject_model=subject,
                judge_model=judge,
                key_file=args.key_file,
                base_url=args.base_url,
                seed=seed,
            )

        return _wrap_recording(factory, args, backend_label="provider", model_label=subject)
    if name == "replay":
        from yarvelle_core.testing.orch_eval.cassette import CassetteBackend
        from yarvelle_core.testing.orch_eval.defaults import DEFAULT_OLLAMA_SUBJECT_MODEL

        root = _cassette_root(args)
        model = args.model or DEFAULT_OLLAMA_SUBJECT_MODEL
        # Recordings from Ollama smoke use backend_label=ollama.
        source_backend = "ollama"

        def factory() -> Any:
            return CassetteBackend(
                cassette_root=root,
                mode="replay",
                inner=None,
                backend_label=source_backend,
                model_label=model,
            )

        return factory
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


def _estimate(selected: Sequence[Tuple[Path, Any]], backend_name: str, samples: int, args: argparse.Namespace) -> int:
    from yarvelle_core.testing.orch_eval.cost import cost_table_for, estimate_run_usd, load_cost_tables
    from yarvelle_core.testing.orch_eval.defaults import (
        DEFAULT_OLLAMA_SUBJECT_MODEL,
        DEFAULT_PROVIDER_SUBJECT_MODEL,
    )

    turns = sum(len(s.turns) for _p, s in selected) / max(len(selected), 1)
    model = args.model or (
        DEFAULT_OLLAMA_SUBJECT_MODEL if backend_name == "ollama" else DEFAULT_PROVIDER_SUBJECT_MODEL
    )
    tables = load_cost_tables()
    table = cost_table_for(model, tables)
    estimate = estimate_run_usd(
        scenarios=len(selected),
        turns_per_scenario=turns,
        samples=samples,
        model_calls_per_turn=3.0,
        input_tokens_per_call=800,
        output_tokens_per_call=400,
        table=table,
    )
    estimate["backend"] = backend_name
    estimate["model"] = model
    print(json.dumps(estimate, indent=2))
    print(
        f"estimate: ~${estimate['usd']:.4f} for {estimate['sut_model_calls']} model calls "
        f"({estimate['input_tokens']} in / {estimate['output_tokens']} out)",
        file=sys.stderr,
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    from yarvelle_core.testing.orch_eval.cost import SpendRefusedError
    from yarvelle_core.testing.orch_eval.driver import run_scenarios
    from yarvelle_core.testing.orch_eval.cassette import CassetteError, CassetteMissError
    from yarvelle_core.testing.orch_eval.ollama_backend import OllamaUnavailableError

    loaded, packs, code = _load_and_lint(args.paths, args.pack)
    if code:
        return code
    wanted = set(args.scenario)
    selected = [(p, s) for p, s in loaded if not wanted or s.id in wanted]
    unknown = sorted(wanted - {s.id for _p, s in loaded})
    if unknown:
        print(f"Unknown scenario id(s): {unknown}", file=sys.stderr)
        return 1
    # Drop scenarios that do not list this backend.
    selected = [(p, s) for p, s in selected if args.backend in s.backends]
    if not selected:
        print(f"No scenario lists the {args.backend!r} backend.", file=sys.stderr)
        return 1
    samples_override = args.samples
    default_samples = selected[0][1].samples_for(args.backend)
    samples = samples_override if samples_override is not None else default_samples
    if getattr(args, "record", False) and args.backend == "replay":
        print("Cannot --record while using --backend replay.", file=sys.stderr)
        return 2
    if getattr(args, "record", False) and args.backend == "fake":
        print("Recording the fake backend is not useful; use ollama or provider.", file=sys.stderr)
        return 2
    if args.estimate:
        return _estimate(selected, args.backend, samples, args)
    try:
        factory = _backend_factory(args.backend, args)
    except SpendRefusedError as err:
        print(str(err), file=sys.stderr)
        return 2
    results: List[Any] = []
    try:
        for pack_id in sorted({s.pack for _p, s in selected}):
            group = [s for _p, s in selected if s.pack == pack_id]
            results.extend(
                asyncio.run(run_scenarios(group, packs[pack_id], factory, samples=samples))
            )
    except OllamaUnavailableError as err:
        print(f"skip: {err}", file=sys.stderr)
        return 0
    except CassetteMissError as err:
        print(f"cassette miss: {err}", file=sys.stderr)
        return 1
    except CassetteError as err:
        print(f"cassette error: {err}", file=sys.stderr)
        return 1
    except SpendRefusedError as err:
        print(str(err), file=sys.stderr)
        return 2
    if not results:
        print(f"No scenario lists the {args.backend!r} backend.", file=sys.stderr)
        return 1
    try:
        describe_backend = factory()
    except Exception:
        describe_backend = None
    document = run_result(results, describe_backend) if describe_backend is not None else {
        "schema": RESULT_SCHEMA_VERSION,
        "backend": {"backend": args.backend},
        "passed": all(r.passed for r in results),
        "totals": {
            "scenarios": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
        "scenarios": [r.to_dict() for r in results],
    }
    if describe_backend is not None and hasattr(describe_backend, "meter"):
        document["spend"] = describe_backend.meter.snapshot()

    from yarvelle_core.testing.orch_eval.baseline import (
        EXIT_REGRESSION,
        compare_runs,
        render_compare_markdown,
        resolve_baseline_ref,
        save_baseline,
    )
    from yarvelle_core.testing.orch_eval.report import (
        default_out_root,
        enrich_document,
        new_run_id,
        write_run_reports,
    )

    root = Path(args.out_dir).expanduser() if args.out_dir else default_out_root()
    backend_name = (document.get("backend") or {}).get("backend") or args.backend
    run_id = new_run_id(str(backend_name))
    run_dir = root / run_id
    started = document.get("started_at") or datetime.now(timezone.utc).isoformat()
    enrich_document(document, run_id=run_id, out_dir=run_dir, started_at=started)

    if not args.no_report:
        write_run_reports(document, run_dir)
        print(f"report: {run_dir}", file=sys.stderr)

    out_text = json.dumps(document, indent=2, sort_keys=False, default=str)
    if args.out:
        Path(args.out).write_text(out_text + "\n", encoding="utf-8")
    print(out_text)
    for r in results:
        sample = getattr(r, "sample", None)
        label = f"{r.scenario_id}" + (f" s{sample}" if sample is not None else "")
        mark = "pass" if r.passed else "FAIL"
        print(f"{mark}  {label}", file=sys.stderr)
        for failure in r.failures():
            print(f"      {failure}", file=sys.stderr)
    totals = document["totals"]
    print(f"{totals['passed']} of {totals['scenarios']} scenario(s) passed.", file=sys.stderr)

    exit_code = 0 if document["passed"] else 1
    if args.baseline:
        try:
            baseline_path = resolve_baseline_ref(args.baseline, root)
            baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError) as err:
            print(f"baseline error: {err}", file=sys.stderr)
            return 1
        compare = compare_runs(
            document,
            baseline_doc,
            check_latency=True if getattr(args, "check_latency", False) else None,
        )
        compare_text = render_compare_markdown(compare)
        if not args.no_report:
            (run_dir / "compare.md").write_text(compare_text + "\n", encoding="utf-8")
            (run_dir / "compare.json").write_text(
                json.dumps(compare.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
        print(compare_text, file=sys.stderr)
        if compare.has_regression:
            exit_code = EXIT_REGRESSION if exit_code == 0 else exit_code
            print(
                f"regression vs baseline {compare.baseline_run_id}: "
                f"{len(compare.regressions)} finding(s)",
                file=sys.stderr,
            )

    if args.save_baseline and document.get("passed") and exit_code == 0:
        saved = save_baseline(run_dir / "results.json", root)
        print(f"baseline saved: {saved}", file=sys.stderr)
    elif args.save_baseline:
        print("baseline not saved: run did not pass cleanly", file=sys.stderr)

    return exit_code


def _baseline_cmd(args: argparse.Namespace) -> int:
    from yarvelle_core.testing.orch_eval.baseline import resolve_baseline_ref, save_baseline
    from yarvelle_core.testing.orch_eval.report import default_out_root

    if args.baseline_command != "save":
        print("usage: ... baseline save <run>", file=sys.stderr)
        return 2
    root = Path(args.out_dir).expanduser() if args.out_dir else default_out_root()
    try:
        results_path = resolve_baseline_ref(args.run, root)
        saved = save_baseline(results_path, root)
    except (OSError, ValueError, FileNotFoundError) as err:
        print(f"baseline error: {err}", file=sys.stderr)
        return 1
    print(f"baseline saved: {saved}")
    return 0


def _compare_cmd(args: argparse.Namespace) -> int:
    from yarvelle_core.testing.orch_eval.baseline import (
        EXIT_REGRESSION,
        compare_runs,
        load_results,
        render_compare_markdown,
        resolve_baseline_ref,
    )
    from yarvelle_core.testing.orch_eval.report import default_out_root

    root = Path(args.out_dir).expanduser() if args.out_dir else default_out_root()
    try:
        current = load_results(resolve_baseline_ref(args.current, root))
        baseline = load_results(resolve_baseline_ref(args.baseline, root))
    except (OSError, ValueError, FileNotFoundError) as err:
        print(f"compare error: {err}", file=sys.stderr)
        return 1
    compare = compare_runs(
        current,
        baseline,
        check_latency=True if getattr(args, "check_latency", False) else None,
    )
    text = render_compare_markdown(compare)
    print(text)
    print(json.dumps(compare.to_dict(), indent=2))
    return EXIT_REGRESSION if compare.has_regression else 0


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
    if args.command == "baseline":
        return _baseline_cmd(args)
    if args.command == "compare":
        return _compare_cmd(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
