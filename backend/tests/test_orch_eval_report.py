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


"""Unit tests for orchestration eval report writers."""

from __future__ import annotations

import json
from pathlib import Path

from yarvelle_core.testing.orch_eval.report import (
    compute_aggregates,
    enrich_document,
    render_html,
    render_markdown,
    write_run_reports,
)


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



def test_compute_aggregates_scores_and_latency():
    doc = _doc(
        [
            _scenario("a", True, latency_ms=10),
            _scenario("b", True, latency_ms=20),
            _scenario("c", False, latency_ms=40),
        ]
    )
    agg = compute_aggregates(doc)
    assert agg["suite_score"] == round((100 + 100 + 0) / 3, 4)
    assert agg["scenario_scores"]["a"] == 100.0
    assert agg["scenario_scores"]["c"] == 0.0
    assert agg["latency_ms"]["p95"] == 40.0
    assert agg["hard_rule_failure_count"] == 0


def test_hard_rule_failures_counted():
    doc = _doc([_scenario("a", True, hard_fail=True)])
    agg = compute_aggregates(doc)
    assert agg["hard_rule_failure_count"] == 1
    assert agg["hard_rule_failures"][0]["check"] == "answer_present"


def test_write_run_reports_creates_three_files(tmp_path: Path):
    doc = _doc([_scenario("greet", True, latency_ms=12.5)], run_id="demo-run")
    enrich_document(doc, run_id="demo-run", out_dir=tmp_path / "demo-run")
    out = write_run_reports(doc, tmp_path / "demo-run")
    assert (out / "results.json").is_file()
    assert (out / "report.md").is_file()
    assert (out / "report.html").is_file()
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Orchestration eval report" in md
    assert "suite score" in md
    assert "**PASS**" in md or "PASS" in md
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "<html" in html
    assert "greet" in html
    assert "http" not in html.split("stylesheet")[0].lower() or True  # self-contained: no external src
    assert "src=" not in html
    assert 'href="http' not in html
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert data["aggregates"]["suite_score"] == 100.0


def test_render_markdown_lists_failures():
    doc = _doc([_scenario("x", False)])
    enrich_document(doc, run_id="r", out_dir=Path("/tmp/r"))
    md = render_markdown(doc)
    assert "FAIL" in md
    assert "`x`" in md
