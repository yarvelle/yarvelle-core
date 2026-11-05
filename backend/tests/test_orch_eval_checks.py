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

"""Unit tests for the orchestration eval checks (pure functions over a trace)."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from yarvelle_core.testing.orch_eval.checks import (
    PackView,
    check_answer,
    check_budget,
    check_continuity,
    check_invariants,
    check_notices,
    check_provenance,
    check_route,
    check_turn,
    leaked_ids,
    text_matches,
)
from yarvelle_core.testing.orch_eval.schema import Turn, TurnExpectation
from yarvelle_core.testing.orch_eval.trace import TaskRecord, TurnTrace

PACK = PackView(
    titles={"trip-organizer": "Trip Organizer", "budget-planner": "Budget Planner", "internal-auditor": "Internal Auditor"},
    hidden=frozenset({"internal-auditor"}),
    max_agents=2,
)


def _trace(**kw: Any) -> TurnTrace:
    base: Dict[str, Any] = {"turn": 1, "user": "u", "route": "main_agent", "answer": "A plan."}
    base.update(kw)
    return TurnTrace(**base)


def _expect(**kw: Any) -> TurnExpectation:
    return TurnExpectation.model_validate(kw)


def _status(results: List[Any]) -> Dict[str, str]:
    return {r.name: r.status for r in results}


def _task(agent: str, *states: str, truncated: bool = False) -> TaskRecord:
    return TaskRecord(task_id=f"t-{agent}", agent_id=agent, states=["started", *states], truncated=truncated)


def test_text_matches_substring_and_regex():
    assert text_matches("austin", "Plan for AUSTIN")
    assert text_matches("/\\$?600/", "under $600")
    assert not text_matches("/^plan$/", "a plan")


def test_leaked_ids_matches_whole_ids_only():
    assert leaked_ids("Ask budget-planner later", ["budget-planner"]) == ["budget-planner"]
    assert leaked_ids("Ask the Budget Planner", ["budget-planner"]) == []
    assert leaked_ids("see budget-planner-2", ["budget-planner"]) == []


def test_route_pass_fail_skip():
    assert check_route(_trace(), _expect(route="main_agent")).status == "pass"
    assert check_route(_trace(route="user_selected"), _expect(route="main_agent")).status == "fail"
    assert check_route(_trace(), _expect()).status == "skip"


def test_invariants_flag_cap_hidden_errors_and_script():
    trace = _trace(
        agents=["internal-auditor"],
        tasks=[_task("a", "completed"), _task("b", "completed"), _task("c", "completed")],
        error="RuntimeError: boom",
        answer="",
        script_problems=["__main__ has 1 unused scripted step(s)"],
    )
    got = _status(check_invariants(trace, PACK))
    assert got["turn_completed"] == "fail"
    assert got["answer_present"] == "fail"
    assert got["task_call_cap"] == "fail"
    assert got["hidden_agents_not_run"] == "fail"
    assert got["fake_script"] == "fail"


def test_invariants_pass_on_clean_turn():
    trace = _trace(
        agents=["trip-organizer"],
        tasks=[_task("trip-organizer", "completed")],
        route_events=["route.main_agent"],
        turn_tasks=[{"task_id": "t-trip-organizer", "state": "completed"}],
    )
    assert all(r.status == "pass" for r in check_invariants(trace, PACK))


def test_provenance_titles_must_match_pack():
    bad = _trace(provenance=[{"agent_id": "trip-organizer", "agent_title": "trip-organizer", "state": "completed"}])
    assert _status(check_invariants(bad, PACK))["provenance_titles"] == "fail"


def test_agents_and_task_calls():
    trace = _trace(agents=["trip-organizer"], tasks=[_task("trip-organizer", "completed")])
    turn = Turn(user="u", expect=_expect(agents_exactly=["trip-organizer", "budget-planner"], max_task_calls=0))
    got = _status(check_turn(trace, turn, PACK))
    assert got["agents_exactly"] == "fail"
    assert got["max_task_calls"] == "fail"
    turn = Turn(user="u", expect=_expect(agents_any_of=["trip-organizer", "budget-planner"], agents_forbidden=["budget-planner"], min_task_calls=1))
    got = _status(check_turn(trace, turn, PACK))
    assert got["agents_any_of"] == "pass" and got["agents_forbidden"] == "pass" and got["min_task_calls"] == "pass"


@pytest.mark.parametrize(
    "mode,earlier,now,ok",
    [
        ("equal", ["a"], ["a"], True),
        ("equal", ["a", "b"], ["a"], False),
        ("subset", ["a", "b"], ["a"], True),
        ("subset", ["a"], [], False),
        ("overlap", ["a", "b"], ["b", "c"], True),
        ("overlap", ["a"], ["c"], False),
    ],
)
def test_continuity_modes(mode, earlier, now, ok):
    expect = _expect(same_agents_as_turn={"turn": 1, "mode": mode})
    result = check_continuity(_trace(turn=2, agents=now), expect, [_trace(agents=earlier)])
    assert result[0].status == ("pass" if ok else "fail")


def test_task_states_use_final_state():
    trace = _trace(agents=["trip-organizer"], tasks=[_task("trip-organizer", "failed")])
    turn = Turn(user="u", expect=_expect(task_states={"trip-organizer": "completed"}))
    assert _status(check_turn(trace, turn, PACK))["task_states"] == "fail"


def test_notices_codes_and_agents():
    trace = _trace(notices=[{"code": "partial_failure", "agent_ids": ["budget-planner"]}])
    assert _status(check_notices(trace, _expect(notices=[])))["notices"] == "fail"
    got = _status(check_notices(trace, _expect(notices=[{"code": "partial_failure", "agent_ids": ["trip-organizer"]}])))
    assert got["notices"] == "pass" and got["notice_agents:partial_failure"] == "fail"
    assert check_notices(trace, _expect()) == []


def test_answer_checks_and_slug_leak():
    trace = _trace(answer="Ask budget-planner about Austin.")
    got = _status(check_answer(trace, _expect(answer={"must_mention": ["austin", "lisbon"], "must_not_mention": ["Austin"]}), PACK))
    assert got["no_agent_ids_in_answer"] == "fail"
    assert got["must_mention:austin"] == "pass" and got["must_mention:lisbon"] == "fail"
    assert got["must_not_mention:Austin"] == "fail"
    off = _status(check_answer(trace, _expect(answer={"no_slug_leak": False}), PACK))
    assert "no_agent_ids_in_answer" not in off


def test_provenance_cite_and_missing_by_title():
    prov = [
        {"agent_id": "trip-organizer", "agent_title": "Trip Organizer", "state": "completed"},
        {"agent_id": "budget-planner", "agent_title": "Budget Planner", "state": "failed"},
    ]
    expect = _expect(provenance={"must_cite": ["trip-organizer"], "must_not_cite": ["internal-auditor"], "missing": ["budget-planner"]})
    named = _trace(provenance=prov, answer="Plan. Budget Planner did not answer.")
    assert all(r.status == "pass" for r in check_provenance(named, expect, PACK))
    unnamed = _trace(provenance=prov, answer="Plan.")
    assert _status(check_provenance(unnamed, expect, PACK))["missing:budget-planner"] == "fail"
    cites_failed = _expect(provenance={"must_cite": ["budget-planner"]})
    assert _status(check_provenance(named, cites_failed, PACK))["cites:budget-planner"] == "fail"


def test_budget_limits():
    trace = _trace(model_calls=5, latency_ms=50.0, input_tokens=10, output_tokens=5, prompt_chars=100)
    got = _status(
        check_budget(
            trace,
            _expect(budget={"model_calls": 4, "latency_ms_p95": 100, "tokens": 15, "usd": 0, "prompt_chars": 80}),
            0.0,
        )
    )
    assert got == {
        "budget:model_calls": "fail",
        "budget:latency_ms": "pass",
        "budget:tokens": "pass",
        "budget:usd": "pass",
        "budget:prompt_chars": "fail",
    }


def test_judge_is_reported_as_skipped():
    turn = Turn.model_validate({"user": "u", "judge": {"rubric": "helpful", "criteria": "is helpful"}})
    got = _status(check_turn(_trace(), turn, PACK))
    assert got["judge:helpful"] == "skip"


def test_model_calls_before_route_and_deliberation():
    turn = Turn(user="u", expect=_expect(model_calls_before_route=0, deliberation=False))
    got = _status(check_turn(_trace(model_calls_before_route=1, nodes=["deliberation"]), turn, PACK))
    assert got["model_calls_before_route"] == "fail" and got["deliberation"] == "fail"
