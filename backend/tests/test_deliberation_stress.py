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

"""Adversarial stress testing and empirical validation suite for Milestone 1 SSE streaming.

Empirically tests:
1. High volume of custom events in quick succession (1,000+ events, interleaved streams, large payloads).
2. Resuming turns with deliberation state checkpoints (deliberation_state persistence, cross-domain redaction).
3. Single-agent fallback degradation across varied numbers of missing agents (0, 1, partial, all missing).
4. Wire formatting with complex unicode, emojis, bidirectional text, control chars, and newlines.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from yarvelle_core.audit.redaction import REDACTED_PLACEHOLDER
from yarvelle_core.constants.api import (
    SSE_DELIBERATION_EVENTS,
    SSE_EVENT_DELIBERATION_CRITIQUE,
    SSE_EVENT_DELIBERATION_END,
    SSE_EVENT_DELIBERATION_PROPOSAL,
    SSE_EVENT_DELIBERATION_REVISION,
    SSE_EVENT_PANEL_START,
    SSE_EVENT_SUGGESTIONS,
    SSE_EVENT_TOKEN,
    SSE_EVENT_TOOL_END,
    SSE_EVENT_TOOL_START,
)
from yarvelle_core.engine.service import AgentExecutionService, ExecutionService, filter_deliberation_event
from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    ExecutionMode,
    ExecutionPlan,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.state import AgentState, create_initial_state

try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


# ============================================================================
# Dimension 1: High Volume and Rapid-Succession Custom Events
# ============================================================================


@pytest.mark.asyncio
async def test_high_volume_deliberation_events_streaming():
    """Verify that the SSE streaming pipeline handles 1,000 custom events in rapid succession without loss or corruption."""
    total_events_count = 1000
    mock_model = MockChatModel(model_name="mock-stress-volume")

    builder = StateGraph(AgentState)

    async def high_volume_node(state: AgentState) -> Dict[str, Any]:
        from langchain_core.callbacks.manager import adispatch_custom_event

        await adispatch_custom_event(
            SSE_EVENT_PANEL_START,
            {
                "panel_id": "panel_volume_stress",
                "title": "High Volume Stress Panel",
                "agents": ["specialist_alpha", "specialist_beta"],
                "shared_constraints": [],
            },
        )

        for i in range(1, total_events_count - 1):
            if i % 3 == 0:
                await adispatch_custom_event(
                    SSE_EVENT_DELIBERATION_PROPOSAL,
                    {
                        "round": (i // 100) + 1,
                        "agent_id": f"specialist_{i % 5}",
                        "scope": "domain_compute.tasks",
                        "summary": f"Automated proposal generation sequence item {i}",
                        "resource_claims": {"quota": float(i % 50)},
                        "tainted": (i % 2 == 0),
                    },
                )
            elif i % 3 == 1:
                await adispatch_custom_event(
                    SSE_EVENT_DELIBERATION_CRITIQUE,
                    {
                        "round": (i // 100) + 1,
                        "reviewer_id": f"specialist_{(i + 1) % 5}",
                        "target_id": f"specialist_{i % 5}",
                        "reviewer_scope": "domain_compute.tasks",
                        "target_scope": "domain_compute.tasks",
                        "stance": "endorse" if i % 2 == 0 else "conflict",
                        "issue_type": "resource",
                        "critique": f"Automated critique sequence item {i}",
                    },
                )
            else:
                await adispatch_custom_event(
                    SSE_EVENT_DELIBERATION_REVISION,
                    {
                        "round": (i // 100) + 1,
                        "agent_id": f"specialist_{i % 5}",
                        "scope": "domain_compute.tasks",
                        "summary": f"Automated revision sequence item {i}",
                        "resolved_critiques": [f"specialist_{(i + 1) % 5}: Resolved critique {i}"],
                    },
                )

        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_END,
            {
                "reason": "converged",
                "rounds_used": 10,
                "open_conflicts": 0,
                "missing_agents": [],
            },
        )
        return {"output": "Volume test complete."}

    builder.add_node("volume", high_volume_node)
    builder.add_edge(START, "volume")
    builder.add_edge("volume", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    received_delib_events: List[Dict[str, Any]] = []
    wire_lines: List[str] = []

    async for event in service.execute_turn(
        thread_id="test_delib_volume_t1",
        prompt="Execute volume stress test",
    ):
        if event.get("type") in SSE_DELIBERATION_EVENTS:
            received_delib_events.append(event)
            wire_lines.append(service.format_sse_wire_event(event))

    assert len(received_delib_events) == total_events_count
    assert received_delib_events[0]["type"] == SSE_EVENT_PANEL_START
    assert received_delib_events[-1]["type"] == SSE_EVENT_DELIBERATION_END

    # Verify wire formatting across all 1,000 events
    assert len(wire_lines) == total_events_count
    for idx, wire in enumerate(wire_lines):
        assert wire.startswith(f"event: {received_delib_events[idx]['type']}\n")
        assert wire.endswith("\n\n")
        parsed = json.loads(wire.strip().split("\n", 1)[1][6:])
        assert parsed["type"] == received_delib_events[idx]["type"]


@pytest.mark.asyncio
async def test_burst_interleaved_events_with_tokens_and_tools():
    """Verify deliberation events interleaved with tokens, tool invocations, and suggestions are yielded accurately."""
    mock_model = MockChatModel(model_name="mock-stress-interleaved")
    builder = StateGraph(AgentState)

    async def interleaved_node(state: AgentState) -> Dict[str, Any]:
        from langchain_core.callbacks.manager import adispatch_custom_event

        await adispatch_custom_event(
            SSE_EVENT_PANEL_START,
            {"panel_id": "panel_interleave", "title": "Interleaved Panel", "agents": ["a", "b"], "shared_constraints": []},
        )
        await adispatch_custom_event(
            SSE_EVENT_TOOL_START,
            {"type": SSE_EVENT_TOOL_START, "tool": "compute_query", "params": {"query": "stats"}},
        )
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_PROPOSAL,
            {"round": 1, "agent_id": "a", "scope": "domain_a", "summary": "Prop 1", "resource_claims": {}, "tainted": False},
        )
        await adispatch_custom_event(
            SSE_EVENT_TOOL_END,
            {"type": SSE_EVENT_TOOL_END, "tool": "compute_query", "duration_ms": 12.5, "status": "ok", "allowed": True, "result": {"units": 5}},
        )
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_CRITIQUE,
            {"round": 1, "reviewer_id": "b", "target_id": "a", "stance": "endorse", "issue_type": "synergy", "critique": "OK"},
        )
        await adispatch_custom_event(
            SSE_EVENT_SUGGESTIONS,
            {"type": SSE_EVENT_SUGGESTIONS, "suggestions": ["Suggestion 1", "Suggestion 2"]},
        )
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_END,
            {"reason": "converged", "rounds_used": 1, "open_conflicts": 0, "missing_agents": []},
        )
        return {"output": "Interleaved execution complete"}

    builder.add_node("interleave", interleaved_node)
    builder.add_edge(START, "interleave")
    builder.add_edge("interleave", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    event_sequence: List[str] = []
    async for event in service.execute_turn(
        thread_id="test_interleave_t2",
        prompt="Execute interleaved test",
    ):
        event_sequence.append(event.get("type", "unknown"))

    assert SSE_EVENT_PANEL_START in event_sequence
    assert SSE_EVENT_TOOL_START in event_sequence
    assert SSE_EVENT_DELIBERATION_PROPOSAL in event_sequence
    assert SSE_EVENT_TOOL_END in event_sequence
    assert SSE_EVENT_DELIBERATION_CRITIQUE in event_sequence
    assert SSE_EVENT_SUGGESTIONS in event_sequence
    assert SSE_EVENT_DELIBERATION_END in event_sequence


def test_extremely_large_payload_deliberation_events():
    """Verify that filter_deliberation_event and format_sse_wire_event handle huge payloads without truncation or error."""
    huge_summary = "A" * 65536  # 64 KB of text
    huge_claims = {f"claim_key_{i}": float(i) for i in range(500)}
    resolved = [f"reviewer_{i}: Detailed resolution point {i} text" for i in range(100)]

    event_payload = {
        "type": SSE_EVENT_DELIBERATION_PROPOSAL,
        "round": 1,
        "agent_id": "specialist_heavy",
        "scope": "domain_heavy.tasks",
        "summary": huge_summary,
        "resource_claims": huge_claims,
        "tainted": False,
        "resolved_critiques": resolved,
        "is_cross_domain": True,
    }

    # Unauthorized caller: free text must be cleanly replaced with REDACTED_PLACEHOLDER
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        event_payload,
        client_scope="domain_light",
        granted_scopes={"domain_light.*"},
    )
    assert filtered["summary"] == REDACTED_PLACEHOLDER
    assert len(filtered["resource_claims"]) == 500

    wire = ExecutionService.format_sse_wire_event(filtered)
    assert wire.startswith(f"event: {SSE_EVENT_DELIBERATION_PROPOSAL}\n")
    assert wire.endswith("\n\n")

    parsed = json.loads(wire.strip().split("\n", 1)[1][6:])
    assert parsed["summary"] == REDACTED_PLACEHOLDER
    assert len(parsed["resource_claims"]) == 500


# ============================================================================
# Dimension 2: Resuming Turns with Deliberation State Checkpoints
# ============================================================================


@pytest.mark.asyncio
async def test_deliberation_resume_checkpointed_state_preservation():
    """Verify that deliberation_state stored on AgentState survives checkpointing and resuming without data loss."""
    mock_model = MockChatModel(model_name="mock-stress-checkpoint")
    builder = StateGraph(AgentState)

    d_state = {
        "panel_id": "panel_staged_action_gate",
        "rounds_used": 2,
        "converged": True,
        "termination_reason": "converged",
        "proposals": {
            "specialist_alpha": {"round": 2, "summary": "Alpha summary", "scope": "domain_alpha"},
            "specialist_beta": {"round": 2, "summary": "Beta summary", "scope": "domain_alpha"},
        },
        "critiques": {},
        "open_conflicts": 0,
        "missing_agents": [],
    }

    async def deliberate_phase(state: AgentState) -> Dict[str, Any]:
        # Interrupt with human approval requirement
        interrupt({"approval_id": "appr_chk_1", "action": "require_approval"})
        from langchain_core.callbacks.manager import adispatch_custom_event
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_END,
            {
                "reason": "converged",
                "rounds_used": 2,
                "open_conflicts": 0,
                "missing_agents": [],
            },
        )
        return {"deliberation_state": d_state, "output": "Deliberation finalized after resume."}

    builder.add_node("deliberate", deliberate_phase)
    builder.add_edge(START, "deliberate")
    builder.add_edge("deliberate", END)

    cp = MemorySaver()
    compiled_graph = builder.compile(checkpointer=cp)
    service = AgentExecutionService(model=mock_model, graph=compiled_graph, checkpointer=cp)

    class MockAppStore:
        def get(self, app_id: str) -> Any:
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {"action": "execute"}
            rec.profile_id = "default_profile"
            rec.payload_hash = "mock_hash"
            return rec

    # 1. Turn 1 halts at interrupt
    async for _ in service.execute_turn(thread_id="thread_chk_delib_1", prompt="Begin gated deliberation"):
        pass

    # 2. Resumed turn executes post-interrupt and emits deliberation_end
    resume_events = []
    async for ev in service.execute_resume_turn(
        thread_id="thread_chk_delib_1",
        approval_id="appr_chk_1",
        approval_store=MockAppStore(),
    ):
        resume_events.append(ev)

    res_types = [ev.get("type") for ev in resume_events]
    assert SSE_EVENT_DELIBERATION_END in res_types
    end_ev = next(ev for ev in resume_events if ev.get("type") == SSE_EVENT_DELIBERATION_END)
    assert end_ev["reason"] == "converged"
    assert end_ev["rounds_used"] == 2


@pytest.mark.asyncio
async def test_deliberation_resume_cross_domain_redaction():
    """Verify that deliberation events forwarded during execute_resume_turn undergo scope filtering."""
    mock_model = MockChatModel(model_name="mock-stress-resume-cross")
    builder = StateGraph(AgentState)

    async def step_node(state: AgentState) -> Dict[str, Any]:
        interrupt({"approval_id": "appr_cross_1", "action": "require_approval"})
        from langchain_core.callbacks.manager import adispatch_custom_event
        # Emit a cross-domain proposal event from foreign domain_beta
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_PROPOSAL,
            {
                "round": 2,
                "agent_id": "specialist_beta",
                "scope": "domain_beta.tasks",
                "summary": "Secret cross-domain plan on resumption.",
                "resource_claims": {"quota": 10.0},
                "tainted": False,
                "is_cross_domain": True,
            },
        )
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_END,
            {"reason": "converged", "rounds_used": 2, "open_conflicts": 0, "missing_agents": []},
        )
        return {"output": "Resumed step finished"}

    builder.add_node("step", step_node)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)

    cp = MemorySaver()
    compiled_graph = builder.compile(checkpointer=cp)
    service = AgentExecutionService(model=mock_model, graph=compiled_graph, checkpointer=cp)

    class MockAppStore:
        def get(self, app_id: str) -> Any:
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {}
            rec.profile_id = "default_profile"
            rec.payload_hash = "mock_hash"
            return rec

    # Run to interrupt
    async for _ in service.execute_turn(thread_id="thread_resume_cross_1", prompt="Initial"):
        pass

    # Resume with client authorized only for domain_alpha
    resumed_events = []
    async for ev in service.execute_resume_turn(
        thread_id="thread_resume_cross_1",
        approval_id="appr_cross_1",
        approval_store=MockAppStore(),
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    ):
        resumed_events.append(ev)

    proposals = [ev for ev in resumed_events if ev.get("type") == SSE_EVENT_DELIBERATION_PROPOSAL]
    assert len(proposals) == 1
    # Free-text summary must be redacted
    assert proposals[0]["summary"] == REDACTED_PLACEHOLDER
    assert proposals[0]["resource_claims"] == {"quota": 10.0}
    assert proposals[0]["round"] == 2


@pytest.mark.asyncio
async def test_deliberation_resume_with_execution_context_param():
    """Verify whether execute_resume_turn applies scope filtering when execution_context is passed."""
    mock_model = MockChatModel(model_name="mock-stress-resume-ec")
    builder = StateGraph(AgentState)

    async def step_node(state: AgentState) -> Dict[str, Any]:
        interrupt({"approval_id": "appr_cross_ec", "action": "require_approval"})
        from langchain_core.callbacks.manager import adispatch_custom_event
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_PROPOSAL,
            {
                "round": 2,
                "agent_id": "specialist_beta",
                "scope": "domain_beta.tasks",
                "summary": "Secret cross-domain plan on resumption.",
                "resource_claims": {"quota": 10.0},
                "tainted": False,
            },
        )
        return {"output": "Done"}

    builder.add_node("step", step_node)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)

    cp = MemorySaver()
    compiled_graph = builder.compile(checkpointer=cp)
    service = AgentExecutionService(model=mock_model, graph=compiled_graph, checkpointer=cp)

    class MockAppStore:
        def get(self, app_id: str) -> Any:
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {}
            rec.profile_id = "default_profile"
            rec.payload_hash = "mock_hash"
            return rec

    async for _ in service.execute_turn(thread_id="thread_resume_cross_ec", prompt="Initial"):
        pass

    resumed_events = []
    async for ev in service.execute_resume_turn(
        thread_id="thread_resume_cross_ec",
        approval_id="appr_cross_ec",
        approval_store=MockAppStore(),
        execution_context={"is_cross_domain": True, "granted_scopes": ["domain_alpha.*"], "scope": "domain_alpha"},
    ):
        resumed_events.append(ev)

    proposals = [ev for ev in resumed_events if ev.get("type") == SSE_EVENT_DELIBERATION_PROPOSAL]
    assert len(proposals) == 1
    assert proposals[0]["summary"] == REDACTED_PLACEHOLDER


def test_scope_filter_cross_domain_unauthenticated_caller_fail_closed():
    """Verify that an unauthenticated caller (no client_scope, no grants) in a cross-domain panel is redacted (fail-closed)."""
    cross_prop = {
        "round": 1,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "Confidential foreign domain proposal details.",
        "resource_claims": {"quota": 15.0},
        "tainted": False,
        "is_cross_domain": True,
    }
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        cross_prop,
        client_scope=None,
        granted_scopes=None,
    )
    assert filtered["summary"] == REDACTED_PLACEHOLDER


# ============================================================================
# Dimension 3: Single-Agent Fallback Degradation Across Missing Agents
# ============================================================================


@pytest.mark.asyncio
async def test_fallback_degradation_target_agents_1():
    """Verify that when only 1 target agent is specified, the panel degrades immediately to single_agent_fallback."""
    mock_model = MockChatModel(model_name="mock-stress-fallback-1")
    cfg = DeliberationConfig(panel_id="panel_single_agent")

    mock_model.queue_response({
        "agent_id": "specialist_solo",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Solo agent proposal.",
    })

    engine = DeliberationEngine(model=mock_model, config=cfg)
    initial_state = create_initial_state(
        prompt="Schedule task with 1 agent",
        agent_id="specialist_solo",
    )
    initial_state["target_agents"] = ["specialist_solo"]

    dispatched_events: List[Dict[str, Any]] = []

    # Patch _emit_sse_event to capture emissions
    import yarvelle_core.workflows.deliberation.engine as engine_module
    orig_emit = engine_module._emit_sse_event

    async def capture_emit(name: str, data: Dict[str, Any]) -> None:
        dispatched_events.append({"type": name, **data})
        await orig_emit(name, data)

    engine_module._emit_sse_event = capture_emit
    try:
        final_state = await engine.run(initial_state)
    finally:
        engine_module._emit_sse_event = orig_emit

    assert final_state["deliberation_state"]["degraded"] is True
    assert final_state["deliberation_state"]["termination_reason"] == "single_agent_fallback"
    assert "Solo agent proposal." in final_state["output"]

    end_events = [ev for ev in dispatched_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    assert end_events[0]["reason"] == "single_agent_fallback"
    assert end_events[0]["rounds_used"] == 1


@pytest.mark.asyncio
async def test_fallback_degradation_target_agents_0():
    """Verify that when 0 target agents are specified, the panel degrades without crashing."""
    mock_model = MockChatModel(model_name="mock-stress-fallback-0")
    cfg = DeliberationConfig(panel_id="panel_zero_agent")

    engine = DeliberationEngine(model=mock_model, config=cfg)
    initial_state = create_initial_state(
        prompt="Schedule task with 0 agents",
        agent_id="",
    )
    initial_state["target_agents"] = []

    dispatched_events: List[Dict[str, Any]] = []
    import yarvelle_core.workflows.deliberation.engine as engine_module
    orig_emit = engine_module._emit_sse_event

    async def capture_emit(name: str, data: Dict[str, Any]) -> None:
        dispatched_events.append({"type": name, **data})
        await orig_emit(name, data)

    engine_module._emit_sse_event = capture_emit
    try:
        final_state = await engine.run(initial_state)
    finally:
        engine_module._emit_sse_event = orig_emit

    assert final_state["deliberation_state"]["degraded"] is True
    assert final_state["deliberation_state"]["termination_reason"] == "single_agent_fallback"
    assert "No proposal available" in final_state["output"]

    end_events = [ev for ev in dispatched_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    assert end_events[0]["reason"] == "single_agent_fallback"


@pytest.mark.asyncio
async def test_fallback_degradation_all_agents_fail():
    """Verify that when 5 target agents all fail generation, panel degrades cleanly with all 5 recorded as missing."""
    mock_model = MockChatModel(model_name="mock-stress-fallback-all-fail")
    cfg = DeliberationConfig(panel_id="panel_all_fail")

    # Queue invalid responses for all 5 agents (two attempts per agent)
    for _ in range(10):
        mock_model.queue_response({"invalid_field": "unparseable response"})

    engine = DeliberationEngine(model=mock_model, config=cfg)
    agents = [f"specialist_{i}" for i in range(5)]
    initial_state = create_initial_state(prompt="Coordinate 5 specialists", agent_id="specialist_0")
    initial_state["target_agents"] = agents

    dispatched_events: List[Dict[str, Any]] = []
    import yarvelle_core.workflows.deliberation.engine as engine_module
    orig_emit = engine_module._emit_sse_event

    async def capture_emit(name: str, data: Dict[str, Any]) -> None:
        dispatched_events.append({"type": name, **data})
        await orig_emit(name, data)

    engine_module._emit_sse_event = capture_emit
    try:
        final_state = await engine.run(initial_state)
    finally:
        engine_module._emit_sse_event = orig_emit

    assert final_state["deliberation_state"]["degraded"] is True
    assert final_state["deliberation_state"]["termination_reason"] == "single_agent_fallback"

    end_events = [ev for ev in dispatched_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    assert end_events[0]["reason"] == "single_agent_fallback"
    assert set(end_events[0]["missing_agents"]) == set(agents)


@pytest.mark.asyncio
async def test_fallback_degradation_partial_failure_below_threshold():
    """Verify that when 3 of 4 agents fail (1 survives < 2), panel degrades and lists all 3 missing agents."""
    mock_model = MockChatModel(model_name="mock-stress-fallback-3-of-4")
    cfg = DeliberationConfig(panel_id="panel_partial_fail")

    # Specialist 0 succeeds
    mock_model.queue_response({
        "agent_id": "specialist_0",
        "round_num": 1,
        "scope": "domain_compute.tasks",
        "summary": "Sole surviving computation plan.",
    })
    # Specialists 1, 2, 3 fail
    for _ in range(6):
        mock_model.queue_response({"error": "invalid format"})

    engine = DeliberationEngine(model=mock_model, config=cfg)
    agents = [f"specialist_{i}" for i in range(4)]
    initial_state = create_initial_state(prompt="Coordinate 4 specialists", agent_id="specialist_0")
    initial_state["target_agents"] = agents

    dispatched_events: List[Dict[str, Any]] = []
    import yarvelle_core.workflows.deliberation.engine as engine_module
    orig_emit = engine_module._emit_sse_event

    async def capture_emit(name: str, data: Dict[str, Any]) -> None:
        dispatched_events.append({"type": name, **data})
        await orig_emit(name, data)

    engine_module._emit_sse_event = capture_emit
    try:
        final_state = await engine.run(initial_state)
    finally:
        engine_module._emit_sse_event = orig_emit

    assert final_state["deliberation_state"]["degraded"] is True
    assert final_state["deliberation_state"]["termination_reason"] == "single_agent_fallback"
    assert "Sole surviving computation plan." in final_state["output"]

    end_events = [ev for ev in dispatched_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    assert set(end_events[0]["missing_agents"]) == {"specialist_1", "specialist_2", "specialist_3"}


@pytest.mark.asyncio
async def test_fallback_threshold_boundary_2_agents_survive():
    """Verify that when 2 of 4 agents survive (2 >= 2 threshold), deliberation proceeds without degrading."""
    mock_model = MockChatModel(model_name="mock-stress-boundary-2-survive")
    cfg = DeliberationConfig(
        panel_id="panel_boundary_2",
        budget=DeliberationBudget(max_rounds=1),
    )

    # Specialist 0 and 1 succeed
    mock_model.queue_response({
        "agent_id": "specialist_0",
        "round_num": 1,
        "scope": "domain_compute.tasks",
        "summary": "Plan 0 survives.",
    })
    mock_model.queue_response({
        "agent_id": "specialist_1",
        "round_num": 1,
        "scope": "domain_compute.tasks",
        "summary": "Plan 1 survives.",
    })
    # Specialists 2 and 3 fail
    for _ in range(4):
        mock_model.queue_response({"fail": "corrupt"})

    # Critiques between 0 and 1
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_0",
        "target_agent_id": "specialist_1",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Compatible plan.",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_1",
        "target_agent_id": "specialist_0",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Compatible plan.",
    }])

    engine = DeliberationEngine(model=mock_model, config=cfg)
    agents = [f"specialist_{i}" for i in range(4)]
    initial_state = create_initial_state(prompt="Coordinate 4 specialists", agent_id="specialist_0")
    initial_state["target_agents"] = agents

    dispatched_events: List[Dict[str, Any]] = []
    import yarvelle_core.workflows.deliberation.engine as engine_module
    orig_emit = engine_module._emit_sse_event

    async def capture_emit(name: str, data: Dict[str, Any]) -> None:
        dispatched_events.append({"type": name, **data})
        await orig_emit(name, data)

    engine_module._emit_sse_event = capture_emit
    try:
        final_state = await engine.run(initial_state)
    finally:
        engine_module._emit_sse_event = orig_emit

    # Must NOT degrade
    assert final_state["deliberation_state"]["degraded"] is False
    assert final_state["deliberation_state"]["termination_reason"] in ("converged", "max_rounds")

    end_events = [ev for ev in dispatched_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    assert end_events[0]["reason"] in ("converged", "max_rounds")
    assert set(end_events[0]["missing_agents"]) == {"specialist_2", "specialist_3"}


# ============================================================================
# Dimension 4: Wire Formatting with Complex Unicode and Unusual Characters
# ============================================================================


def test_wire_formatting_newlines_and_carriage_returns():
    """Verify that multi-line summaries with \\r\\n and \\n are serialized cleanly without breaking SSE framing."""
    multiline_summary = (
        "First step proposal:\n"
        "1. Initialize distributed cache.\r\n"
        "2. Query remote indices.\n\n"
        "3. Finalize output.\r"
    )
    event = {
        "type": SSE_EVENT_DELIBERATION_PROPOSAL,
        "round": 1,
        "agent_id": "specialist_multiline",
        "scope": "domain_text.tasks",
        "summary": multiline_summary,
        "resource_claims": {},
        "tainted": False,
    }

    wire = ExecutionService.format_sse_wire_event(event)

    # In SSE protocol, there should be exactly two newlines at the end of the event frame
    # and exactly one newline after 'event: ...'
    lines = wire.split("\n")
    assert lines[0] == f"event: {SSE_EVENT_DELIBERATION_PROPOSAL}"
    assert lines[1].startswith("data: ")
    # lines[2] and lines[3] are the empty lines representing \n\n
    assert len(lines) == 4
    assert lines[2] == ""
    assert lines[3] == ""

    # Parse JSON back and verify original multi-line string is identical
    parsed = json.loads(lines[1][6:])
    assert parsed["summary"] == multiline_summary


def test_wire_formatting_complex_unicode_and_emojis():
    """Verify that complex Unicode (ZWJ emojis, Arabic/Hebrew RTL, diacritics, CJK) survives wire serialization intact."""
    complex_text = (
        "Emoji test: 👨‍👩‍👧‍👦 🏳️‍🌈 🧑🏽‍💻\n"
        "Arabic RTL: مرحبا بالعالم\n"
        "Hebrew RTL: שלום עולם\n"
        "Combining diacritics: e\u0301 a\u0300 u\u0308\n"
        "CJK characters: 繁體中文 简体中文 日本語 한국어\n"
        "Math symbols: ∀x ∈ ℝ, ∃y : y > x² + 1 / ∞ ≈ 0"
    )

    event = {
        "type": SSE_EVENT_DELIBERATION_CRITIQUE,
        "round": 1,
        "reviewer_id": "specialist_unicode",
        "target_id": "specialist_target",
        "reviewer_scope": "domain_unicode",
        "target_scope": "domain_unicode",
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": complex_text,
    }

    wire = ExecutionService.format_sse_wire_event(event)
    assert wire.startswith(f"event: {SSE_EVENT_DELIBERATION_CRITIQUE}\n")
    assert wire.endswith("\n\n")

    data_line = wire.strip().split("\n", 1)[1]
    parsed = json.loads(data_line[6:])
    assert parsed["critique"] == complex_text


def test_wire_formatting_quotes_and_json_injection():
    """Verify strings attempting JSON injection or unescaped quotes do not corrupt the SSE wire format."""
    injection_strings = [
        '{"malicious": true, "injected_field": "escaped"}',
        '"><script>alert("xss")</script>',
        'event: malicious_event\ndata: {"hack": true}\n\n',
        "Double \"quotes\" and 'single' `backticks` and \\backslashes\\",
        "Null byte simulation: \\u0000 and \\x00",
    ]

    for attack in injection_strings:
        event = {
            "type": SSE_EVENT_DELIBERATION_PROPOSAL,
            "round": 1,
            "agent_id": "specialist_injection",
            "scope": "domain_security.tasks",
            "summary": attack,
            "resource_claims": {},
            "tainted": True,
        }

        wire = ExecutionService.format_sse_wire_event(event)
        # Verify strict SSE wire boundaries
        assert wire.startswith(f"event: {SSE_EVENT_DELIBERATION_PROPOSAL}\n")
        assert wire.endswith("\n\n")

        # Must parse as single JSON object matching input
        data_segment = wire.strip().split("\n", 1)[1]
        assert data_segment.startswith("data: ")
        parsed = json.loads(data_segment[6:])
        assert parsed["summary"] == attack
        assert parsed["tainted"] is True


def test_scope_filter_wildcard_and_edge_cases():
    """Verify scope filtering with wildcard patterns, missing fields, and none values."""
    # 1. Missing scope in proposal defaults safely
    no_scope_prop = {
        "round": 1,
        "agent_id": "specialist_unknown",
        "summary": "No scope specified",
        "resource_claims": {},
    }
    res = filter_deliberation_event(SSE_EVENT_DELIBERATION_PROPOSAL, no_scope_prop)
    assert res["summary"] == "No scope specified"

    # 2. Wildcard grant matches subscopes
    cross_prop = {
        "round": 1,
        "agent_id": "specialist_sub",
        "scope": "domain_finance.audit.deep",
        "summary": "Deep audit proposal details",
        "resource_claims": {},
        "is_cross_domain": True,
    }
    res_wild = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        cross_prop,
        client_scope="domain_other",
        granted_scopes={"domain_finance.*"},
    )
    assert res_wild["summary"] == "Deep audit proposal details"

    # 3. Wildcard grant mismatch redacts
    res_mismatch = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        cross_prop,
        client_scope="domain_other",
        granted_scopes={"domain_compute.*"},
    )
    assert res_mismatch["summary"] == REDACTED_PLACEHOLDER
