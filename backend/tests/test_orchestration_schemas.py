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

"""Unit tests for the orchestration data contracts (plan, tasks, routing, stream, audit)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest
from pydantic import TypeAdapter, ValidationError
import yaml

from yarvelle_core.constants.api import SSE_ORCHESTRATION_EVENTS
from yarvelle_core.pack.spec import PackManifest, PackSpec
from yarvelle_core.schemas.a2a import A2AMessage, TextPart
from yarvelle_core.schemas.orchestration import (
    DEFAULT_AGENT_TIMEOUT_S,
    DEFAULT_MAX_AGENTS,
    DEFAULT_TURN_TIMEOUT_S,
    ORCHESTRATION_SCHEMA_VERSION,
    AgentTaskEnvelope,
    AgentTaskResult,
    FixedRoute,
    GuardrailFlagTrigger,
    HasAttachmentsTrigger,
    OrchestrationAuditRecord,
    OrchestrationLimits,
    OrchestrationPlan,
    OrchestrationStreamEvent,
    PackOrchestrationSpec,
    RouteDecision,
    RouteSource,
    SSEOrchestrationNoticeEvent,
    SSEOrchestrationPlanEvent,
    SSETaskStatusEvent,
    TaskStatus,
    audit_durability,
    content_sha256,
)
from yarvelle_core.schemas.plan import ExecutionMode

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
IN_HASH = content_sha256("input")


def _steps(*agents: str, deps: Dict[int, List[int]] | None = None) -> List[Dict[str, Any]]:
    deps = deps or {}
    return [
        {"step_id": f"s{i}", "agent_id": a, "depends_on": [f"s{d}" for d in deps.get(i, [])]}
        for i, a in enumerate(agents)
    ]


def _plan(mode: str, steps: List[Dict[str, Any]], **kw: Any) -> OrchestrationPlan:
    return OrchestrationPlan.model_validate({"mode": mode, "steps": steps, **kw})


def _prov(**kw: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "agent_id": "agent-a",
        "plan_id": "p1",
        "step_id": "s0",
        "turn_id": "turn-1",
        "input_hash": IN_HASH,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def test_limits_defaults() -> None:
    limits = OrchestrationLimits()
    assert (limits.max_agents, limits.agent_timeout_s, limits.turn_timeout_s) == (4, 60.0, 120.0)
    assert (DEFAULT_MAX_AGENTS, DEFAULT_AGENT_TIMEOUT_S, DEFAULT_TURN_TIMEOUT_S) == (4, 60.0, 120.0)


@pytest.mark.parametrize(
    "data",
    [
        {"max_agents": 0},
        {"max_agents": 17},
        {"agent_timeout_s": 0},
        {"turn_timeout_s": -1},
        {"agent_timeout_s": 90, "turn_timeout_s": 60},
        {"unknown": 1},
    ],
)
def test_limits_reject_invalid(data: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OrchestrationLimits.model_validate(data)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def test_single_plan() -> None:
    plan = _plan("single", _steps("agent-a"), rationale="one agent covers it")
    assert plan.schema_version == ORCHESTRATION_SCHEMA_VERSION
    assert plan.mode is ExecutionMode.SINGLE
    assert plan.execution_order() == [["s0"]]
    assert plan.agent_ids() == ["agent-a"]


def test_parallel_plan_runs_in_one_wave() -> None:
    plan = _plan("parallel", _steps("agent-a", "agent-b", "agent-c"))
    assert plan.execution_order() == [["s0", "s1", "s2"]]


def test_pipeline_plan_orders_waves_deterministically() -> None:
    plan = _plan("pipeline", _steps("agent-a", "agent-b", "agent-c", "agent-d", deps={1: [0], 2: [0], 3: [1, 2]}))
    assert plan.execution_order() == [["s0"], ["s1", "s2"], ["s3"]]


def test_deliberate_plan_with_panel() -> None:
    plan = _plan("deliberate", _steps("agent-a", "agent-b"), panel_id="review-panel")
    assert plan.panel_id == "review-panel"


def test_clarification_plan_has_question_and_no_steps() -> None:
    plan = _plan("single", [], needs_clarification=True, clarification_question="Which account?")
    assert plan.steps == []
    with pytest.raises(ValidationError, match="clarification_question is required"):
        _plan("single", [], needs_clarification=True)
    with pytest.raises(ValidationError, match="must not contain steps"):
        _plan("single", _steps("agent-a"), needs_clarification=True, clarification_question="?")
    with pytest.raises(ValidationError, match="only allowed when needs_clarification"):
        _plan("single", _steps("agent-a"), clarification_question="?")


@pytest.mark.parametrize(
    ("mode", "steps", "message"),
    [
        ("single", [], "at least one step"),
        ("single", _steps("agent-a", "agent-b"), "exactly one step"),
        ("parallel", _steps("agent-a"), "at least two steps"),
        ("pipeline", _steps("agent-a"), "at least two steps"),
        ("deliberate", _steps("agent-a"), "at least two steps"),
        ("parallel", _steps("agent-a", "agent-b", deps={1: [0]}), "only allowed in pipeline"),
        ("deliberate", _steps("agent-a", "agent-b", deps={1: [0]}), "only allowed in pipeline"),
        ("pipeline", _steps("agent-a", "agent-b"), "requires at least one dependency"),
        ("pipeline", _steps("agent-a", "agent-b", deps={0: [1], 1: [0]}), "dependency cycle"),
        ("pipeline", _steps("agent-a", "agent-b", deps={1: [1]}), "depends on itself"),
        ("deliberate", _steps("agent-a", "agent-a"), "distinct agents"),
    ],
)
def test_plan_rejects_invalid_topology(mode: str, steps: List[Dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _plan(mode, steps)


def test_plan_rejects_unknown_and_duplicate_steps() -> None:
    steps = _steps("agent-a", "agent-b")
    steps[1]["depends_on"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown step 'missing'"):
        _plan("pipeline", steps)
    dup = _steps("agent-a", "agent-b")
    dup[1]["step_id"] = "s0"
    with pytest.raises(ValidationError, match="duplicate step ids"):
        _plan("parallel", dup)


def test_plan_rejects_bad_ids_and_panel_outside_deliberate() -> None:
    with pytest.raises(ValidationError, match="Invalid agent id"):
        _plan("single", [{"step_id": "s0", "agent_id": "bad id!"}])
    with pytest.raises(ValidationError):
        _plan("single", [{"step_id": "S 0", "agent_id": "agent-a"}])
    with pytest.raises(ValidationError, match="panel_id is only allowed"):
        _plan("parallel", _steps("agent-a", "agent-b"), panel_id="review-panel")
    with pytest.raises(ValidationError):
        _plan("single", _steps("agent-a"), confidence=0.9)


def test_plan_limit_violations() -> None:
    plan = _plan("parallel", _steps(*[f"agent-{i}" for i in range(5)]))
    assert plan.limit_violations(OrchestrationLimits()) == ["plan has 5 steps; the limit is 4"]
    assert plan.limit_violations(OrchestrationLimits(max_agents=5)) == []


def test_plan_round_trips_through_json() -> None:
    plan = _plan("pipeline", _steps("agent-a", "agent-b", deps={1: [0]}), rationale="b needs a")
    restored = OrchestrationPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert json.loads(plan.model_dump_json())["mode"] == "pipeline"


def test_plan_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        _plan("single", _steps("agent-a"), schema_version=2)


# ---------------------------------------------------------------------------
# Task envelope and result
# ---------------------------------------------------------------------------


def _envelope(**kw: Any) -> AgentTaskEnvelope:
    data: Dict[str, Any] = {
        "task_id": "task-1",
        "turn_id": "turn-1",
        "thread_id": "thread-1",
        "plan_id": "p1",
        "step_id": "s0",
        "agent_id": "agent-a",
        "message": A2AMessage(role="user", parts=[TextPart(text="do it")], task_id="task-1").model_dump(),
    }
    data.update(kw)
    return AgentTaskEnvelope.model_validate(data)


def test_envelope_round_trip_and_defaults() -> None:
    env = _envelope(upstream_task_ids=["task-0"])
    assert env.timeout_s == DEFAULT_AGENT_TIMEOUT_S
    assert AgentTaskEnvelope.model_validate_json(env.model_dump_json()) == env


def test_envelope_rejects_inconsistent_message() -> None:
    agent_msg = A2AMessage(role="agent", parts=[TextPart(text="x")]).model_dump()
    with pytest.raises(ValidationError, match="role must be 'user'"):
        _envelope(message=agent_msg)
    other = A2AMessage(role="user", parts=[TextPart(text="x")], task_id="task-9").model_dump()
    with pytest.raises(ValidationError, match="must match the envelope task_id"):
        _envelope(message=other)
    with pytest.raises(ValidationError, match="cannot list itself"):
        _envelope(upstream_task_ids=["task-1"])
    with pytest.raises(ValidationError, match="timezone-aware"):
        _envelope(created_at=datetime(2026, 1, 1))


def test_completed_result() -> None:
    result = AgentTaskResult(
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        output_text="answer",
        started_at=T0,
        ended_at=T0 + timedelta(seconds=2),
        provenance=_prov(output_hash=content_sha256("answer"), model="local/model"),
    )
    assert result.duration_ms == 2000.0
    assert AgentTaskResult.model_validate_json(result.model_dump_json()) == result


def test_status_set_is_closed() -> None:
    assert {s.value for s in TaskStatus} == {"completed", "failed", "timed_out", "skipped"}
    with pytest.raises(ValidationError):
        AgentTaskResult.model_validate({"task_id": "t", "status": "cancelled", "provenance": _prov()})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"status": "completed", "provenance": _prov()}, "require output_text"),
        (
            {"status": "completed", "output_text": "x", "provenance": _prov(output_hash="0" * 64)},
            "output_hash must be the SHA-256",
        ),
        (
            {
                "status": "completed",
                "output_text": "x",
                "error_code": "boom",
                "provenance": _prov(output_hash=content_sha256("x")),
            },
            "cannot carry error_code",
        ),
        ({"status": "failed", "provenance": _prov()}, "require error_code"),
        ({"status": "timed_out", "output_text": "partial", "error_code": "timeout", "provenance": _prov()}, "cannot carry output"),
        ({"status": "failed", "error_code": "boom", "provenance": _prov(output_hash=IN_HASH)}, "only completed"),
        ({"status": "failed", "error_code": "boom", "provenance": _prov(input_hash=None)}, "require provenance.input_hash"),
        ({"status": "skipped", "provenance": _prov()}, "require skip_reason"),
        ({"status": "skipped", "skip_reason": "upstream failed", "started_at": T0, "provenance": _prov()}, "cannot carry output"),
        (
            {
                "status": "failed",
                "error_code": "boom",
                "started_at": T0,
                "ended_at": T0 - timedelta(seconds=1),
                "provenance": _prov(),
            },
            "ended_at cannot be earlier",
        ),
    ],
)
def test_result_rejects_inconsistent_status(data: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AgentTaskResult.model_validate({"task_id": "task-1", **data})


def test_failed_timed_out_and_skipped_results() -> None:
    failed = AgentTaskResult(task_id="t1", status="failed", error_code="agent.unavailable", provenance=_prov())
    timed = AgentTaskResult(task_id="t2", status="timed_out", error_code="timeout", provenance=_prov())
    skipped = AgentTaskResult(
        task_id="t3", status="skipped", skip_reason="upstream step s0 failed", provenance=_prov(input_hash=None)
    )
    assert [r.status for r in (failed, timed, skipped)] == [TaskStatus.FAILED, TaskStatus.TIMED_OUT, TaskStatus.SKIPPED]
    assert skipped.duration_ms is None


# ---------------------------------------------------------------------------
# Pack routing config
# ---------------------------------------------------------------------------

ORCH_YAML = """
default_agent: general-helper
fixed_routes:
  - route_id: attachments
    when: {kind: has_attachments, mime_types: ["application/pdf", "image/*"]}
    agent_id: document-extractor
  - route_id: urgent
    when: {kind: guardrail_flag, flag: urgent}
    agent_id: urgent-responder
limits:
  max_agents: 3
  agent_timeout_s: 45
  turn_timeout_s: 90
"""


def test_pack_orchestration_spec_from_yaml() -> None:
    spec = PackOrchestrationSpec.model_validate(yaml.safe_load(ORCH_YAML))
    assert isinstance(spec.fixed_routes[0].when, HasAttachmentsTrigger)
    assert isinstance(spec.fixed_routes[1].when, GuardrailFlagTrigger)
    assert spec.limits.max_agents == 3
    assert spec.referenced_agent_ids() == ["general-helper", "document-extractor", "urgent-responder"]


def test_pack_orchestration_defaults() -> None:
    spec = PackOrchestrationSpec(default_agent="general-helper")
    assert spec.fixed_routes == []
    assert spec.limits == OrchestrationLimits()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "default_agent"),
        ({"default_agent": "bad id"}, "Invalid agent id"),
        ({"default_agent": "a", "unknown_key": True}, "Extra inputs"),
        (
            {
                "default_agent": "a",
                "fixed_routes": [
                    {"route_id": "r", "when": {"kind": "has_attachments"}, "agent_id": "b"},
                    {"route_id": "r", "when": {"kind": "has_attachments"}, "agent_id": "c"},
                ],
            },
            "duplicate fixed route ids",
        ),
        (
            {
                "default_agent": "a",
                "fixed_routes": [
                    {"route_id": "r1", "when": {"kind": "guardrail_flag", "flag": "f"}, "agent_id": "b"},
                    {"route_id": "r2", "when": {"kind": "guardrail_flag", "flag": "f"}, "agent_id": "c"},
                ],
            },
            "more than one fixed route",
        ),
        (
            {"default_agent": "a", "fixed_routes": [{"route_id": "r", "when": {"kind": "keyword"}, "agent_id": "b"}]},
            "does not match any of the expected tags",
        ),
    ],
)
def test_pack_orchestration_rejects_invalid(data: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        PackOrchestrationSpec.model_validate(data)


def test_attachment_trigger_rejects_bad_media_type() -> None:
    with pytest.raises(ValidationError, match="Invalid media type"):
        FixedRoute.model_validate(
            {"route_id": "r", "when": {"kind": "has_attachments", "mime_types": ["pdf"]}, "agent_id": "b"}
        )


def test_pack_manifest_and_spec_accept_orchestration_block() -> None:
    manifest = PackManifest.model_validate(
        {
            "id": "sample",
            "name": "Sample",
            "version": "0.1.0",
            "domain": "sample",
            "requires_core": ">=0.1.0",
            "orchestration": yaml.safe_load(ORCH_YAML),
        }
    )
    assert manifest.orchestration is not None
    assert manifest.orchestration.default_agent == "general-helper"
    spec = PackSpec(
        id="sample",
        name="Sample",
        version="0.1.0",
        domain="sample",
        requires_core=">=0.1.0",
        orchestration=manifest.orchestration,
    )
    assert spec.orchestration == manifest.orchestration
    without_block = PackManifest(id="sample", name="Sample", version="0.1.0", domain="sample", requires_core=">=0.1.0")
    assert without_block.orchestration is None


def test_route_decision_rules() -> None:
    RouteDecision(source=RouteSource.PLANNER)
    RouteDecision(source="fixed_route", route_id="attachments")
    RouteDecision(source="default_agent", fallback_reason="planner_unavailable")
    RouteDecision(source="default_agent", fallback_reason="planning_failed")
    with pytest.raises(ValidationError, match="route_id is required"):
        RouteDecision(source="fixed_route")
    with pytest.raises(ValidationError, match="fallback_reason is required"):
        RouteDecision(source="default_agent")
    with pytest.raises(ValidationError, match="fallback_reason is required"):
        RouteDecision(source="planner", fallback_reason="planning_failed")


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


def test_stream_event_names_match_constants() -> None:
    names = {SSEOrchestrationPlanEvent.model_fields["type"].default,
             SSETaskStatusEvent.model_fields["type"].default,
             SSEOrchestrationNoticeEvent.model_fields["type"].default}
    assert names == set(SSE_ORCHESTRATION_EVENTS)


def test_plan_event_from_plan_omits_instructions() -> None:
    plan = _plan("parallel", [{"step_id": "s0", "agent_id": "agent-a", "instructions": "secret detail"},
                              {"step_id": "s1", "agent_id": "agent-b"}])
    event = SSEOrchestrationPlanEvent.from_plan(plan, turn_id="turn-1")
    assert event.steps == [{"step_id": "s0", "agent_id": "agent-a"}, {"step_id": "s1", "agent_id": "agent-b"}]
    assert "secret detail" not in event.model_dump_json()
    with pytest.raises(ValidationError):
        SSEOrchestrationPlanEvent(turn_id="t", plan_id="p", mode="single", steps=[{"step_id": "s0"}])


def test_stream_union_discriminates_by_type() -> None:
    adapter = TypeAdapter(OrchestrationStreamEvent)
    status = adapter.validate_python(
        {"type": "task_status", "turn_id": "t", "task_id": "k", "step_id": "s0", "agent_id": "a", "state": "timed_out"}
    )
    assert isinstance(status, SSETaskStatusEvent)
    notice = adapter.validate_python(
        {"type": "orchestration_notice", "turn_id": "t", "code": "planning_failed", "message": "Used the default agent."}
    )
    assert isinstance(notice, SSEOrchestrationNoticeEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "token", "delta": "x"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"type": "task_status", "turn_id": "t", "task_id": "k", "step_id": "s0", "agent_id": "a", "state": "streaming"}
        )
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "orchestration_notice", "turn_id": "t", "code": "other", "message": "x"})


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("plan.created", "strict"),
        ("plan.rejected", "strict"),
        ("plan.fallback", "strict"),
        ("route.fixed", "strict"),
        ("task.started", "strict"),
        ("task.timed_out", "strict"),
        ("tool.called", "strict"),
        ("synthesis.completed", "strict"),
        ("telemetry.stream", "best_effort"),
    ],
)
def test_audit_durability(event: str, expected: str) -> None:
    assert audit_durability(event) == expected


def test_audit_record_with_bodies_and_redaction() -> None:
    record = OrchestrationAuditRecord(
        event="task.completed",
        thread_id="thread-1",
        turn_id="turn-1",
        plan_id="p1",
        task_id="task-1",
        agent_id="agent-a",
        input_hash=content_sha256("in"),
        output_hash=content_sha256("out"),
        input_body="in",
        output_body="out",
        duration_ms=12.5,
    )
    assert record.durability == "strict"
    stripped = record.without_bodies()
    assert stripped.input_body is None and stripped.output_body is None
    assert stripped.input_hash == record.input_hash and stripped.output_hash == record.output_hash
    assert OrchestrationAuditRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"event": "task.started", "agent_id": "a"}, "require task_id and agent_id"),
        ({"event": "plan.created"}, "require plan_id"),
        ({"event": "tool.called", "task_id": "k"}, "require tool and task_id"),
        ({"event": "telemetry.stream", "output_body": "x"}, "output_hash must be"),
        ({"event": "telemetry.stream", "input_body": "x", "input_hash": "0" * 64}, "input_hash must be"),
        ({"event": "run"}, "Input should be"),
        ({"event": "telemetry.stream", "duration_ms": -1}, "greater than or equal"),
    ],
)
def test_audit_record_rejects_invalid(data: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OrchestrationAuditRecord.model_validate({"thread_id": "thread-1", "turn_id": "turn-1", **data})


def test_committed_pack_schema_includes_orchestration() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schema = json.loads((repo_root / "schemas" / "pack.schema.json").read_text(encoding="utf-8"))
    assert "orchestration" in schema["properties"]
    assert "PackOrchestrationSpec" in schema["$defs"]
