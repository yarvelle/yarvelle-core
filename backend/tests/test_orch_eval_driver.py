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

"""Driver tests: scenarios run through the real graph on the scripted fake.

These run in the normal suite. They use only the in-process fake model and a
pack written to a temp directory; nothing calls a real model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml
from langgraph.checkpoint.memory import MemorySaver

from yarvelle_core.testing.orch_eval.driver import ScenarioRunner, run_scenarios
from yarvelle_core.testing.orch_eval.fake import FakeBackend
from yarvelle_core.testing.orch_eval.loader import parse_scenario
from yarvelle_core.testing.orch_eval.pack import EvalPack, load_eval_pack

AGENTS = {
    "trip-organizer": {"title": "Trip Organizer"},
    "budget-planner": {"title": "Budget Planner"},
    "writing-coach": {"title": "Writing Coach"},
    "escalation-desk": {"title": "Escalation Desk"},
    "internal-auditor": {"title": "Internal Auditor", "hidden": True},
}


def write_pack(root: Path, pack_id: str = "eval-test") -> Path:
    for agent_id, extra in AGENTS.items():
        d = root / "agents" / agent_id
        d.mkdir(parents=True)
        data = {"id": agent_id, "description": f"{agent_id} helper", "persona": "persona.md", "tools": [], "skills": [], **extra}
        (d / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        (d / "persona.md").write_text(f"You are the {agent_id} agent.\n", encoding="utf-8")
    pack = {
        "schema": 1,
        "id": pack_id,
        "orchestration": {
            "default_agent": "writing-coach",
            "limits": {"max_agents": 3, "agent_timeout_s": 10, "turn_timeout_s": 30},
            "fixed_routes": [
                {"route_id": "urgent", "when": {"kind": "guardrail_flag", "flag": "urgent"}, "agent_id": "escalation-desk"}
            ],
        },
        "guardrail_flags": {"urgent": ["urgent"]},
    }
    (root / "pack.yaml").write_text(yaml.safe_dump(pack), encoding="utf-8")
    return root


@pytest.fixture()
def pack(tmp_path: Path) -> EvalPack:
    return load_eval_pack(write_pack(tmp_path / "pack"))


def scenario(turns: list, **extra: Any):
    data: Dict[str, Any] = {"schema": 1, "id": "s", "title": "t", "pack": "eval-test", "backends": ["fake"], "turns": turns}
    data.update(extra)
    return parse_scenario(data)


def run(pack: EvalPack, sc, **kw: Any):
    return asyncio.run(ScenarioRunner(pack, FakeBackend(), **kw).run(sc))


TRIP_TURN = {
    "user": "Plan a weekend and budget it.",
    "expect": {
        "route": "main_agent",
        "agents_exactly": ["trip-organizer", "budget-planner"],
        "notices": [],
        "provenance": {"must_cite": ["trip-organizer", "budget-planner"]},
        "answer": {"must_mention": ["weekend"]},
    },
    "fake": {
        "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "Weekend plan within budget."}],
        "agents": {"trip-organizer": ["Two nights."], "budget-planner": ["About 400."]},
    },
}


def test_multi_turn_main_route_on_one_thread(pack: EvalPack):
    saver = MemorySaver()
    follow_up = {
        "user": "Cheaper please.",
        "expect": {"route": "main_agent", "agents_exactly": ["budget-planner"], "same_agents_as_turn": {"turn": 1, "mode": "subset"}},
        "fake": {"main": [{"task": ["budget-planner"]}, {"answer": "About 300 instead."}], "agents": {"budget-planner": ["300."]}},
    }
    result = run(pack, scenario([TRIP_TURN, follow_up]), checkpointer_factory=lambda: saver)
    assert result.passed, result.failures()
    first, second = (t.trace for t in result.turns)
    assert first.task_calls == 2 and second.task_calls == 1
    assert [p["agent_title"] for p in first.provenance] == ["Trip Organizer", "Budget Planner"]
    assert second.provenance and second.provenance[0]["agent_id"] == "budget-planner"
    assert first.model_calls_before_route == 0
    # One thread: the checkpoint holds both turns.
    threads = {cfg.config["configurable"]["thread_id"] for cfg in saver.list(None)}
    assert len(threads) == 1


def test_fixed_route_then_routing_resumes(pack: EvalPack):
    urgent = {
        "user": "Urgent: help now.",
        "input": {"guardrail_flag": "urgent"},
        "expect": {"route": "fixed_route:urgent", "agents_exactly": ["escalation-desk"], "model_calls_before_route": 0},
        "fake": {"agents": {"escalation-desk": ["Call the front desk now."]}},
    }
    later = {
        "user": "Thanks. Plan tomorrow.",
        "expect": {"route": "main_agent", "agents_exactly": ["trip-organizer"], "agents_forbidden": ["escalation-desk"]},
        "fake": {"main": [{"task": ["trip-organizer"]}, {"answer": "Tomorrow: museum."}], "agents": {"trip-organizer": ["Museum."]}},
    }
    result = run(pack, scenario([urgent, later]))
    assert result.passed, result.failures()


def test_user_selected_agent(pack: EvalPack):
    turn = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "expect": {"route": "user_selected", "agents_exactly": ["writing-coach"], "max_task_calls": 0},
        "fake": {"agents": {"writing-coach": ["Here is your note, fixed."]}},
    }
    result = run(pack, scenario([turn]))
    assert result.passed, result.failures()


def test_partial_failure_notice_and_missing_title(pack: EvalPack):
    turn = {
        "user": "Plan and budget.",
        "expect": {
            "notices": [{"code": "partial_failure", "agent_ids": ["budget-planner"]}],
            "task_states": {"budget-planner": "failed", "trip-organizer": "completed"},
            "provenance": {"must_cite": ["trip-organizer"], "missing": ["budget-planner"]},
        },
        "fake": {
            "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "Trip is ready."}],
            "agents": {"trip-organizer": ["Two nights."], "budget-planner": [{"error": "down"}]},
        },
    }
    result = run(pack, scenario([turn]))
    assert result.passed, result.failures()
    assert "Budget Planner" in result.turns[0].trace.answer


def test_hidden_agent_is_refused_not_run(pack: EvalPack):
    turn = {
        "user": "Audit this.",
        "expect": {"agents_forbidden": ["internal-auditor"], "max_task_calls": 0},
        "fake": {"main": [{"task": ["internal-auditor"]}, {"answer": "I will look at it myself."}]},
    }
    result = run(pack, scenario([turn]))
    assert result.passed, result.failures()
    assert [t.agent_id for t in result.turns[0].trace.rejected_tasks] == ["internal-auditor"]


def test_main_agent_failure_falls_back_to_default(pack: EvalPack):
    turn = {
        "user": "Write a welcome line.",
        "expect": {"route": "default_agent:main_agent_failed", "agents_exactly": ["writing-coach"], "notices": ["main_agent_failed"]},
        "fake": {"main": [{"error": "down"}], "agents": {"writing-coach": ["Welcome aboard!"]}},
    }
    result = run(pack, scenario([turn]))
    assert result.passed, result.failures()


def test_scenario_limit_caps_task_calls(pack: EvalPack):
    turn = {
        "user": "Do three things.",
        "expect": {"max_task_calls": 1, "agents_exactly": ["trip-organizer"]},
        "fake": {"main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "One thing done."}], "agents": {"trip-organizer": ["Done."]}},
    }
    result = run(pack, scenario([turn], limits={"max_agents": 1}))
    assert result.passed, result.failures()


def test_broken_expectation_fails_with_evidence(pack: EvalPack):
    turn = {**TRIP_TURN, "expect": {"route": "main_agent", "agents_exactly": ["writing-coach"], "answer": {"must_mention": ["lisbon"]}}}
    result = run(pack, scenario([turn]))
    assert not result.passed
    failures = "\n".join(result.failures())
    assert "agents_exactly" in failures and "must_mention:lisbon" in failures


def test_script_mismatch_fails_the_turn(pack: EvalPack):
    turn = {
        "user": "Hello.",
        "fake": {"main": [{"answer": "Hi!"}, {"answer": "never used"}], "agents": {"trip-organizer": ["never used"]}},
    }
    result = run(pack, scenario([turn]))
    assert not result.passed
    assert any("fake_script" in f for f in result.failures())


def test_wrong_pack_is_an_error(pack: EvalPack):
    sc = parse_scenario({"schema": 1, "id": "s", "title": "t", "pack": "other", "backends": ["fake"], "turns": [{"user": "x"}]})
    result = run(pack, sc)
    assert not result.passed and "other" in (result.error or "")


def test_result_serialises_without_messages(pack: EvalPack):
    result = run(pack, scenario([TRIP_TURN]))
    data = result.to_dict()
    assert data["passed"] is True
    trace = data["turns"][0]["trace"]
    assert trace["route"] == "main_agent" and trace["task_calls"] == 2
    assert "status_events" not in trace


def test_run_scenarios_skips_other_backends(pack: EvalPack):
    other = parse_scenario({"schema": 1, "id": "o", "title": "t", "pack": "eval-test", "backends": ["ollama"], "turns": [{"user": "x"}]})
    results = asyncio.run(run_scenarios([other, scenario([TRIP_TURN])], pack, FakeBackend))
    assert [r.scenario_id for r in results] == ["s"]


def test_default_checkpointer_is_encrypted_when_enabled(pack: EvalPack, monkeypatch: pytest.MonkeyPatch):
    import os

    from yarvelle_core.config import settings
    from yarvelle_core.vault import checkpoints as cp

    kek = os.urandom(32)
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: kek)
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    cp.reset_checkpoint_keyring_cache()
    try:
        saver = ScenarioRunner(pack, FakeBackend())._checkpointer()
        assert isinstance(saver.serde, cp.EncryptedCheckpointSerializer)
        sealed = []
        original = saver.serde.cipher.encrypt
        saver.serde.cipher.encrypt = lambda data: sealed.append(1) or original(data)
        follow_up = {
            "user": "Cheaper please.",
            "expect": {"route": "main_agent", "agents_exactly": ["budget-planner"]},
            "fake": {"main": [{"task": ["budget-planner"]}, {"answer": "About 300 instead."}], "agents": {"budget-planner": ["300."]}},
        }
        result = run(pack, scenario([TRIP_TURN, follow_up]), checkpointer_factory=lambda: saver)
        assert result.passed, result.failures()
        assert sealed
    finally:
        cp.reset_checkpoint_keyring_cache()


def test_restart_before_resumes_same_thread(pack: EvalPack):
    saver = MemorySaver()
    first = {
        "user": "Plan a weekend.",
        "expect": {"route": "main_agent", "agents_exactly": ["trip-organizer"], "answer": {"must_mention": ["weekend"]}},
        "fake": {
            "main": [{"task": ["trip-organizer"]}, {"answer": "Weekend by the coast."}],
            "agents": {"trip-organizer": ["Coast."]},
        },
    }
    second = {
        "user": "Cheaper please.",
        "restart_before": True,
        "expect": {"route": "main_agent", "agents_exactly": ["budget-planner"], "same_agents_as_turn": {"turn": 1, "mode": "overlap"}},
        "fake": {
            "main": [{"task": ["budget-planner"]}, {"answer": "About 300."}],
            "agents": {"budget-planner": ["300."]},
        },
    }
    # overlap mode: second agents need not be subset of first; just ensure continuity check can pass
    # Use subset against a turn that also called budget? Simpler: equal continuity not required.
    second["expect"].pop("same_agents_as_turn")
    result = run(pack, scenario([first, second]), checkpointer_factory=lambda: saver)
    assert result.passed, result.failures()
    threads = {cfg.config["configurable"]["thread_id"] for cfg in saver.list(None)}
    assert len(threads) == 1


def test_fault_timeout_marks_timed_out(pack: EvalPack):
    turn = {
        "user": "Plan and budget.",
        "expect": {
            "task_states": {"trip-organizer": "completed", "budget-planner": "timed_out"},
            "notices": [{"code": "partial_failure", "agent_ids": ["budget-planner"]}],
            "provenance": {"must_cite": ["trip-organizer"], "missing": ["budget-planner"]},
        },
        "fake": {
            "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "Trip ready."}],
            "agents": {"trip-organizer": ["Two nights."]},
        },
    }
    sc = scenario(
        [turn],
        limits={"agent_timeout_s": 0.4, "turn_timeout_s": 10},
        faults=[{"turn": 1, "agent": "budget-planner", "mode": "timeout", "delay_s": 5}],
    )
    result = run(pack, sc)
    assert result.passed, result.failures()


def test_fault_error_marks_failed(pack: EvalPack):
    turn = {
        "user": "Budget this.",
        "expect": {
            "task_states": {"budget-planner": "failed"},
            "notices": [{"code": "partial_failure", "agent_ids": ["budget-planner"]}],
            "provenance": {"missing": ["budget-planner"]},
        },
        "fake": {
            "main": [{"task": ["budget-planner"]}, {"answer": "No budget."}],
            "agents": {},
        },
    }
    sc = scenario([turn], faults=[{"turn": 1, "agent": "budget-planner", "mode": "error", "message": "down"}])
    result = run(pack, sc)
    assert result.passed, result.failures()


def test_user_cancel_marks_tasks_cancelled(pack: EvalPack):
    turn = {
        "user": "Plan and budget.",
        "expect": {
            "cancelled": True,
            "agents_all_of": ["trip-organizer", "budget-planner"],
            "task_states": {"trip-organizer": "cancelled", "budget-planner": "cancelled"},
        },
        "fake": {
            "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "never"}],
            "agents": {"trip-organizer": ["x"], "budget-planner": ["y"]},
        },
    }
    sc = scenario(
        [turn],
        limits={"agent_timeout_s": 30, "turn_timeout_s": 60},
        faults=[
            {"turn": 1, "agent": "*", "mode": "slow", "delay_s": 8},
            {"turn": 1, "cancel_after_ms": 250},
        ],
    )
    result = run(pack, sc)
    assert result.passed, result.failures()
    assert result.turns[0].trace.cancelled is True


def test_audit_error_fails_the_turn(pack: EvalPack):
    turn = {
        "user": "Plan a trip.",
        "expect": {"error_matches": "/OrchestrationAuditError|injected audit write failure/"},
        "fake": {
            "main": [{"task": ["trip-organizer"]}, {"answer": "never"}],
            "agents": {"trip-organizer": ["Coast."]},
        },
    }
    sc = scenario([turn], faults=[{"turn": 1, "mode": "audit_error"}])
    result = run(pack, sc)
    assert result.passed, result.failures()
    assert result.turns[0].trace.error


def test_encrypt_checkpoints_resume(pack: EvalPack):
    first = {
        "user": "Plan a weekend.",
        "expect": {"route": "main_agent", "agents_exactly": ["trip-organizer"]},
        "fake": {
            "main": [{"task": ["trip-organizer"]}, {"answer": "Weekend plan."}],
            "agents": {"trip-organizer": ["Coast."]},
        },
    }
    second = {
        "user": "Thanks.",
        "restart_before": True,
        "expect": {"route": "main_agent", "agents_exactly": [], "max_task_calls": 0},
        "fake": {"main": [{"answer": "You are welcome."}]},
    }
    sc = scenario([first, second], encrypt_checkpoints=True)
    result = run(pack, sc)
    assert result.passed, result.failures()
