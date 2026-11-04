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

"""Unit tests for the orchestration data contracts (limits, routing, stream, audit)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest
from pydantic import TypeAdapter, ValidationError
import yaml

from yarvelle_core.constants.api import SSE_ORCHESTRATION_EVENTS
from yarvelle_core.pack.spec import PackManifest, PackSpec
from yarvelle_core.schemas.audit import AuditEvent, audit_durability
from yarvelle_core.schemas.orchestration import (
    DEFAULT_AGENT_TIMEOUT_S,
    DEFAULT_MAX_AGENTS,
    DEFAULT_TURN_TIMEOUT_S,
    FixedRoute,
    GuardrailFlagTrigger,
    HasAttachmentsTrigger,
    OrchestrationLimits,
    OrchestrationStreamEvent,
    PackOrchestrationSpec,
    RouteDecision,
    RouteSource,
    SSEOrchestrationNoticeEvent,
    SSETaskStatusEvent,
)

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
    RouteDecision(source=RouteSource.MAIN_AGENT)
    RouteDecision(source="fixed_route", route_id="attachments", agent_id="document-extractor")
    RouteDecision(source="default_agent", fallback_reason="model_unavailable")
    RouteDecision(source="default_agent", fallback_reason="main_agent_failed")
    with pytest.raises(ValidationError, match="route_id is required"):
        RouteDecision(source="fixed_route")
    with pytest.raises(ValidationError, match="fallback_reason is required"):
        RouteDecision(source="default_agent")
    with pytest.raises(ValidationError, match="fallback_reason is required"):
        RouteDecision(source="main_agent", fallback_reason="main_agent_failed")
    with pytest.raises(ValidationError, match="Invalid agent id"):
        RouteDecision(source="main_agent", agent_id="bad id")
    with pytest.raises(ValidationError):
        RouteDecision(source="planner")


def test_route_decision_folds_into_audit_details() -> None:
    decision = RouteDecision(source="fixed_route", route_id="attachments", agent_id="document-extractor")
    event = AuditEvent(agent_id="document-extractor", event="route.fixed", details=decision.to_audit_payload())
    assert event.details == {
        "route": {"source": "fixed_route", "route_id": "attachments", "agent_id": "document-extractor"}
    }
    assert RouteDecision.model_validate(event.details["route"]) == decision


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


def test_stream_event_names_match_constants() -> None:
    names = {SSETaskStatusEvent.model_fields["type"].default,
             SSEOrchestrationNoticeEvent.model_fields["type"].default}
    assert names == set(SSE_ORCHESTRATION_EVENTS)
    assert "orchestration_plan" not in SSE_ORCHESTRATION_EVENTS


def test_stream_union_discriminates_by_type() -> None:
    adapter = TypeAdapter(OrchestrationStreamEvent)
    status = adapter.validate_python(
        {"type": "task_status", "turn_id": "t", "task_id": "call-1", "agent_id": "a", "state": "timed_out"}
    )
    assert isinstance(status, SSETaskStatusEvent)
    notice = adapter.validate_python(
        {"type": "orchestration_notice", "turn_id": "t", "code": "main_agent_failed", "message": "Used the default agent."}
    )
    assert isinstance(notice, SSEOrchestrationNoticeEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "orchestration_plan", "turn_id": "t", "plan_id": "p", "mode": "single"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "token", "delta": "x"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"type": "task_status", "turn_id": "t", "task_id": "call-1", "agent_id": "a", "state": "skipped"}
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"type": "task_status", "turn_id": "t", "task_id": "call-1", "step_id": "s0", "agent_id": "a", "state": "started"}
        )
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "orchestration_notice", "turn_id": "t", "code": "planning_failed", "message": "x"})


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("route.fixed", "strict"),
        ("route.default", "strict"),
        ("task.started", "strict"),
        ("task.completed", "strict"),
        ("task.failed", "strict"),
        ("task.timed_out", "strict"),
        ("run", "best_effort"),
        ("tool", "best_effort"),
        ("synthesis", "best_effort"),
    ],
)
def test_audit_durability(event: str, expected: str) -> None:
    assert audit_durability(event) == expected


def test_audit_event_carries_task_hand_off_fields() -> None:
    event = AuditEvent(
        agent_id="agent-a",
        event="task.completed",
        thread_id="thread-1",
        turn_id="turn-1",
        task_id="call-1",
        input_hash="a" * 64,
        output_hash="b" * 64,
        duration_ms=12.5,
    )
    assert AuditEvent.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "data",
    [
        {"event": "plan.created"},
        {"event": "task.skipped"},
        {"event": "task.completed", "input_hash": "not-a-hash"},
        {"event": "task.failed", "error_code": "Bad Code"},
    ],
)
def test_audit_event_rejects_invalid_orchestration_fields(data: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AuditEvent.model_validate({"agent_id": "agent-a", **data})


def test_committed_pack_schema_includes_orchestration() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for path in (repo_root / "schemas" / "pack.schema.json",
                 repo_root / "backend" / "src" / "yarvelle_core" / "schemas" / "pack.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert "orchestration" in schema["properties"]
        assert "PackOrchestrationSpec" in schema["$defs"]
        assert "OrchestrationPlan" not in schema["$defs"]
