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


"""Unit tests for orchestration eval baseline compare thresholds."""

from __future__ import annotations

import json
from pathlib import Path

from yarvelle_core.testing.orch_eval.baseline import (
    EXIT_REGRESSION,
    Thresholds,
    compare_runs,
    save_baseline,
)
from yarvelle_core.testing.orch_eval.report import enrich_document


def _scenario(sid: str, passed: bool, latency_ms: float = 10.0, hard_fail: bool = False):
    checks = [{"name": "route", "status": "pass" if passed else "fail", "detail": ""}]
    if hard_fail:
        checks.append({"name": "answer_present", "status": "fail", "detail": "empty"})
    elif passed:
        checks.append({"name": "answer_present", "status": "pass", "detail": ""})
    return {
        "id": sid,
        "title": sid,
        "backend": "fake",
        "sample": 1,
        "passed": passed and not hard_fail,
        "error": None,
        "skipped_turns": 0,
        "failures": [] if (passed and not hard_fail) else ["turn 1: answer_present: empty"],
        "turns": [
            {
                "turn": 1,
                "passed": passed and not hard_fail,
                "checks": checks,
                "trace": {
                    "turn": 1,
                    "user": "hi",
                    "route": "main_agent",
                    "agents": ["planner"],
                    "tasks": [{"agent_id": "planner", "final_state": "completed"}],
                    "notices": [],
                    "answer": "ok" if passed and not hard_fail else "",
                    "latency_ms": latency_ms,
                },
            }
        ],
    }


def _doc(scenarios, *, run_id="run-a", cost=0.0):
    passed = sum(1 for s in scenarios if s["passed"])
    return {
        "schema": 1,
        "run_id": run_id,
        "backend": {"backend": "fake", "subject_model": "scripted"},
        "passed": passed == len(scenarios),
        "totals": {"scenarios": len(scenarios), "passed": passed, "failed": len(scenarios) - passed},
        "spend": {"usd": cost, "input_tokens": 0, "output_tokens": 0},
        "scenarios": scenarios,
    }



def _enriched(scenarios, run_id, cost=0.0, out: Path | None = None):
    doc = _doc(scenarios, run_id=run_id, cost=cost)
    return enrich_document(doc, run_id=run_id, out_dir=out or Path(f"/tmp/{run_id}"))


def test_no_regression_when_equal():
    base = _enriched([_scenario("a", True, 10), _scenario("b", True, 12)], "base")
    cur = _enriched([_scenario("a", True, 11), _scenario("b", True, 13)], "cur")
    result = compare_runs(cur, base)
    assert not result.has_regression


def test_hard_rule_is_regression():
    base = _enriched([_scenario("a", True)], "base")
    cur = _enriched([_scenario("a", True, hard_fail=True)], "cur")
    result = compare_runs(cur, base)
    assert result.has_regression
    assert any(r.kind == "hard_rule" for r in result.regressions)


def test_scenario_drop_of_ten_points():
    base = _enriched([_scenario("a", True), _scenario("b", True)], "base")
    # a fails -> 0 vs 100 = 100 point drop (>=10)
    cur = _enriched([_scenario("a", False), _scenario("b", True)], "cur")
    result = compare_runs(cur, base)
    assert any(r.kind == "scenario_score" and r.scenario == "a" for r in result.regressions)
    assert any(r.kind == "suite_score" for r in result.regressions)


def test_suite_drop_threshold_five_points():
    # 20 scenarios: fail 1 -> suite drops 5.0 points exactly -> regression
    scenarios_base = [_scenario(f"s{i}", True) for i in range(20)]
    scenarios_cur = [_scenario(f"s{i}", i != 0) for i in range(20)]
    base = _enriched(scenarios_base, "base")
    cur = _enriched(scenarios_cur, "cur")
    result = compare_runs(cur, base, Thresholds(scenario_drop_points=1000))  # ignore per-scenario
    assert any(r.kind == "suite_score" for r in result.regressions)


def test_latency_p95_skipped_for_fake_by_default():
    """Fake/replay/ollama runs skip the p95 rule unless a flag asks for it."""
    base = _enriched([_scenario("a", True, latency_ms=100)], "base")
    cur = _enriched([_scenario("a", True, latency_ms=130)], "cur")  # +30%
    result = compare_runs(cur, base)
    assert not any(r.kind == "latency_p95" for r in result.regressions)


def test_latency_p95_enforced_when_flagged():
    base = _enriched([_scenario("a", True, latency_ms=100)], "base")
    cur = _enriched([_scenario("a", True, latency_ms=130)], "cur")  # +30%
    result = compare_runs(cur, base, check_latency=True)
    assert any(r.kind == "latency_p95" for r in result.regressions)


def test_latency_p95_enforced_for_provider_by_default():
    base = _enriched([_scenario("a", True, latency_ms=100)], "base")
    cur = _enriched([_scenario("a", True, latency_ms=130)], "cur")  # +30%
    # Switch the documented backend to the paid provider.
    base["backend"] = {"backend": "provider", "subject_model": "gpt-test"}
    cur["backend"] = {"backend": "provider", "subject_model": "gpt-test"}
    result = compare_runs(cur, base)
    assert any(r.kind == "latency_p95" for r in result.regressions)


def test_latency_p95_skipped_for_replay_and_ollama():
    for name in ("replay", "ollama"):
        base = _enriched([_scenario("a", True, latency_ms=100)], "base")
        cur = _enriched([_scenario("a", True, latency_ms=200)], "cur")
        base["backend"] = {"backend": name, "subject_model": "qwen3:8b"}
        cur["backend"] = {"backend": name, "subject_model": "qwen3:8b"}
        result = compare_runs(cur, base)
        assert not any(r.kind == "latency_p95" for r in result.regressions), name


def test_cost_rise_20_percent():
    base = _enriched([_scenario("a", True)], "base", cost=1.0)
    cur = _enriched([_scenario("a", True)], "cur", cost=1.25)
    result = compare_runs(cur, base)
    assert any(r.kind == "cost" for r in result.regressions)


def test_save_baseline_and_compare_cli_helpers(tmp_path: Path):
    run_dir = tmp_path / "runs" / "demo"
    doc = _enriched([_scenario("a", True)], "demo", out=run_dir)
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(json.dumps(doc), encoding="utf-8")
    saved = save_baseline(run_dir / "results.json", tmp_path / "runs")
    assert saved.is_file()
    loaded = json.loads(saved.read_text(encoding="utf-8"))
    assert loaded["run_id"] == "demo"


def test_exit_regression_constant():
    assert EXIT_REGRESSION == 2
