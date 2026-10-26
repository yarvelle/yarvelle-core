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

"""Comprehensive test suite for Phase 2 Deliberation SSE Streaming Pipeline.

Verifies ADR 0001 §2.3, §2.12, and §7 Phase 2 requirements:
1. SSE wire protocol formatting (event: <name>\\ndata: <json>\\n\\n).
2. Same-domain panels emit full unredacted fields across all deliberation events.
3. Cross-domain panels redact free-text (summary, critique, resolved_critiques) to '[REDACTED]'
   for unauthorized client scopes while preserving all structured numeric/typed metadata.
4. Multi-scope authorized callers (stewards) view full unredacted payloads across domains.
5. End-to-end SSE turn execution yields all 5 deliberation custom events with 'type' field.
6. Multi-round revision streaming populates resolved_critiques from addressed prior critiques.
7. Fallback degradation (< 2 proposals) emits deliberation_end with reason='single_agent_fallback'.
8. Resumed turn execution (execute_resume_turn) forwards deliberation custom events.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
import pytest
from langgraph.graph import END, START, StateGraph

from yarvelle_core.audit.redaction import REDACTED_PLACEHOLDER
from yarvelle_core.constants.api import (
    SSE_DELIBERATION_EVENTS,
    SSE_EVENT_DELIBERATION_CRITIQUE,
    SSE_EVENT_DELIBERATION_END,
    SSE_EVENT_DELIBERATION_PROPOSAL,
    SSE_EVENT_DELIBERATION_REVISION,
    SSE_EVENT_PANEL_START,
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
# 1. SSE Wire Protocol Formatting Tests
# ============================================================================


def test_sse_wire_formatting_deliberation_events():
    """Verify format_sse_wire_event formats each deliberation event as event: <name>\\ndata: <json>\\n\\n."""
    test_events = [
        {
            "type": SSE_EVENT_PANEL_START,
            "panel_id": "panel_alpha",
            "title": "Computation Deliberation",
            "agents": ["specialist_alpha", "specialist_beta"],
            "shared_constraints": [{"id": "resource_quota", "limit_value": 50.0}],
            "scopes": ["domain_alpha.tasks"],
        },
        {
            "type": SSE_EVENT_DELIBERATION_PROPOSAL,
            "round": 1,
            "agent_id": "specialist_alpha",
            "scope": "domain_alpha.tasks",
            "summary": "Execute step 1 requiring 20 units.",
            "resource_claims": {"resource_quota": 20.0},
            "tainted": False,
        },
        {
            "type": SSE_EVENT_DELIBERATION_CRITIQUE,
            "round": 1,
            "reviewer_id": "specialist_beta",
            "target_id": "specialist_alpha",
            "reviewer_scope": "domain_alpha.tasks",
            "target_scope": "domain_alpha.tasks",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Resource claim aligns with budget limits.",
        },
        {
            "type": SSE_EVENT_DELIBERATION_REVISION,
            "round": 2,
            "agent_id": "specialist_alpha",
            "scope": "domain_alpha.tasks",
            "summary": "Revised step 1 requiring 15 units.",
            "resolved_critiques": ["specialist_beta: Resource claim aligns with budget limits."],
        },
        {
            "type": SSE_EVENT_DELIBERATION_END,
            "reason": "converged",
            "rounds_used": 2,
            "open_conflicts": 0,
            "missing_agents": [],
        },
    ]

    for ev in test_events:
        wire_str = ExecutionService.format_sse_wire_event(ev)
        ev_type = ev["type"]

        # Must strictly start with "event: <type>\n"
        assert wire_str.startswith(f"event: {ev_type}\n"), f"Expected wire chunk to start with event: {ev_type}"
        # Must terminate with "\n\n"
        assert wire_str.endswith("\n\n"), "Expected SSE chunk to terminate with double newline"

        # Parse data segment
        lines = wire_str.strip().split("\n", 1)
        assert len(lines) == 2
        assert lines[0] == f"event: {ev_type}"
        assert lines[1].startswith("data: ")

        data_json = lines[1][6:]
        parsed_payload = json.loads(data_json)
        assert parsed_payload["type"] == ev_type
        for k, v in ev.items():
            assert parsed_payload[k] == v


def test_sse_deliberation_events_tuple_constants():
    """Verify SSE_DELIBERATION_EVENTS contains all 5 deliberation event constants."""
    assert len(SSE_DELIBERATION_EVENTS) == 5
    assert SSE_EVENT_PANEL_START in SSE_DELIBERATION_EVENTS
    assert SSE_EVENT_DELIBERATION_PROPOSAL in SSE_DELIBERATION_EVENTS
    assert SSE_EVENT_DELIBERATION_CRITIQUE in SSE_DELIBERATION_EVENTS
    assert SSE_EVENT_DELIBERATION_REVISION in SSE_DELIBERATION_EVENTS
    assert SSE_EVENT_DELIBERATION_END in SSE_DELIBERATION_EVENTS


# ============================================================================
# 2. Scope-Filtering Logic Unit Tests
# ============================================================================


def test_scope_filter_same_domain_panel_preserves_full_fields():
    """Verify same-domain panels preserve all free-text fields without redaction."""
    prop_data = {
        "round": 1,
        "agent_id": "specialist_alpha",
        "scope": "domain_alpha.tasks",
        "summary": "Unrestricted proposal summary for same domain.",
        "resource_claims": {"quota": 10.0},
        "tainted": False,
    }
    filtered_prop = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        prop_data,
        execution_context={"is_cross_domain": False, "scope": "domain_alpha"},
    )
    assert filtered_prop["summary"] == "Unrestricted proposal summary for same domain."
    assert filtered_prop["resource_claims"] == {"quota": 10.0}

    critique_data = {
        "round": 1,
        "reviewer_id": "specialist_alpha",
        "target_id": "specialist_beta",
        "reviewer_scope": "domain_alpha.tasks",
        "target_scope": "domain_alpha.tasks",
        "stance": "conflict",
        "issue_type": "resource",
        "critique": "Unrestricted critique text within same domain.",
    }
    filtered_critique = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_CRITIQUE,
        critique_data,
        execution_context={"is_cross_domain": False},
    )
    assert filtered_critique["critique"] == "Unrestricted critique text within same domain."

    rev_data = {
        "round": 2,
        "agent_id": "specialist_beta",
        "scope": "domain_alpha.tasks",
        "summary": "Revised plan in same domain.",
        "resolved_critiques": ["specialist_alpha: Unrestricted critique text within same domain."],
    }
    filtered_rev = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_REVISION,
        rev_data,
        execution_context={"is_cross_domain": False},
    )
    assert filtered_rev["summary"] == "Revised plan in same domain."
    assert filtered_rev["resolved_critiques"] == ["specialist_alpha: Unrestricted critique text within same domain."]


def test_scope_filter_cross_domain_redacts_unauthorized_proposals():
    """Verify cross-domain panels redact free-text summaries to [REDACTED] for unauthorized scopes."""
    unauth_prop = {
        "round": 1,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "Confidential foreign domain proposal details.",
        "resource_claims": {"quota": 15.0},
        "tainted": False,
    }
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        unauth_prop,
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert filtered["summary"] == REDACTED_PLACEHOLDER
    assert filtered["resource_claims"] == {"quota": 15.0}
    assert filtered["tainted"] is False
    assert filtered["agent_id"] == "specialist_beta"
    assert filtered["round"] == 1


def test_scope_filter_cross_domain_redacts_unauthorized_revisions():
    """Verify cross-domain panels redact summary and resolved_critiques on revisions for unauthorized scopes."""
    unauth_rev = {
        "round": 2,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "Confidential revision summary.",
        "resolved_critiques": ["specialist_alpha: Confidential addressed critique details."],
    }
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_REVISION,
        unauth_rev,
        execution_context={"is_cross_domain": True, "granted_scopes": ["domain_alpha.*"]},
    )
    assert filtered["summary"] == REDACTED_PLACEHOLDER
    assert filtered["resolved_critiques"] == [REDACTED_PLACEHOLDER]
    assert filtered["agent_id"] == "specialist_beta"
    assert filtered["round"] == 2


def test_scope_filter_cross_domain_redacts_unauthorized_critiques():
    """Verify cross-domain critiques redact critique text while preserving stance and metadata."""
    cross_critique = {
        "round": 1,
        "reviewer_id": "specialist_alpha",
        "target_id": "specialist_beta",
        "reviewer_scope": "domain_alpha.tasks",
        "target_scope": "domain_beta.tasks",
        "stance": "conflict",
        "issue_type": "resource",
        "critique": "Confidential critique text targeting domain_beta.",
    }
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_CRITIQUE,
        cross_critique,
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert filtered["critique"] == REDACTED_PLACEHOLDER
    assert filtered["stance"] == "conflict"
    assert filtered["issue_type"] == "resource"
    assert filtered["reviewer_id"] == "specialist_alpha"
    assert filtered["target_id"] == "specialist_beta"
    assert filtered["reviewer_scope"] == "domain_alpha.tasks"
    assert filtered["target_scope"] == "domain_beta.tasks"


def test_scope_filter_cross_domain_authorized_steward_sees_all():
    """Verify an authorized steward with wildcard or multi-scope grant sees full text across domains."""
    steward_grants = {"*"}

    cross_prop = {
        "round": 1,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "Full summary visible to authorized steward.",
        "resource_claims": {"quota": 10.0},
        "tainted": False,
        "is_cross_domain": True,
    }
    filtered_prop = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        cross_prop,
        client_scope="domain_alpha",
        granted_scopes=steward_grants,
    )
    assert filtered_prop["summary"] == "Full summary visible to authorized steward."

    cross_critique = {
        "round": 1,
        "reviewer_id": "specialist_alpha",
        "target_id": "specialist_beta",
        "reviewer_scope": "domain_alpha.tasks",
        "target_scope": "domain_beta.tasks",
        "stance": "amend",
        "issue_type": "scope",
        "critique": "Full critique text visible to authorized steward.",
    }
    filtered_critique = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_CRITIQUE,
        cross_critique,
        client_scope="domain_alpha",
        granted_scopes=steward_grants,
    )
    assert filtered_critique["critique"] == "Full critique text visible to authorized steward."


# ============================================================================
# 3. End-to-End Turn Streaming Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_deliberation_turn_streaming_emits_all_custom_events_end_to_end():
    """Verify execute_turn yields all 5 deliberation custom events with proper 'type' and filtered payloads."""
    mock_model = MockChatModel(model_name="mock-deliberate-stream")

    constraint = SharedConstraint(
        id="compute_quota",
        description="Total compute units allowable",
        unit="units",
        limit_value=30.0,
        limit_source="user",
    )
    cfg = DeliberationConfig(
        panel_id="panel_streaming_e2e",
        shared_constraints=[constraint],
        budget=DeliberationBudget(max_rounds=2),
        critique_mode="per_agent",
    )

    # Queue mock responses: 2 proposals + 2 endorse critiques -> converges in 1 round
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Execute compute task 1 with 12 units.",
        "recommendations": ["Init step 1"],
        "resource_claims": {"compute_quota": 12.0},
        "resource_claim_units": {"compute_quota": "units"},
    })
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Execute compute task 2 with 10 units.",
        "recommendations": ["Init step 2"],
        "resource_claims": {"compute_quota": 10.0},
        "resource_claim_units": {"compute_quota": "units"},
    })
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Compatible with compute quota.",
        "proposed_resolution": "Adopt",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Compatible with compute quota.",
        "proposed_resolution": "Adopt",
    }])

    engine = DeliberationEngine(model=mock_model, config=cfg)

    # Build StateGraph connecting deliberation engine
    async def deliberate_node(s: AgentState) -> Dict[str, Any]:
        return await engine.run(s)

    builder = StateGraph(AgentState)
    builder.add_node("deliberate", deliberate_node)
    builder.add_edge(START, "deliberate")
    builder.add_edge("deliberate", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    plan = ExecutionPlan(
        mode=ExecutionMode.DELIBERATE,
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg,
    )

    yielded_events: List[Dict[str, Any]] = []
    async for event in service.execute_turn(
        thread_id="test_delib_stream_t1",
        prompt="Schedule distributed computation",
        execution_plan=plan,
        target_agents=["specialist_alpha", "specialist_beta"],
    ):
        yielded_events.append(event)

    # Verify event types yielded
    event_types = [ev.get("type") for ev in yielded_events]

    assert SSE_EVENT_PANEL_START in event_types
    assert SSE_EVENT_DELIBERATION_PROPOSAL in event_types
    assert SSE_EVENT_DELIBERATION_CRITIQUE in event_types
    assert SSE_EVENT_DELIBERATION_END in event_types

    # Verify panel_start payload
    start_ev = next(ev for ev in yielded_events if ev.get("type") == SSE_EVENT_PANEL_START)
    assert start_ev["panel_id"] == "panel_streaming_e2e"
    assert "specialist_alpha" in start_ev["agents"]
    assert "specialist_beta" in start_ev["agents"]
    assert len(start_ev["shared_constraints"]) == 1
    assert "scopes" in start_ev

    # Verify deliberation_proposal payloads have required keys
    proposal_events = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_PROPOSAL]
    assert len(proposal_events) == 2
    for pev in proposal_events:
        assert pev["round"] == 1
        assert "agent_id" in pev
        assert "scope" in pev
        assert "summary" in pev
        assert "resource_claims" in pev
        assert "tainted" in pev

    # Verify deliberation_critique payloads have required keys
    critique_events = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_CRITIQUE]
    assert len(critique_events) >= 2
    for cev in critique_events:
        assert cev["round"] == 1
        assert "reviewer_id" in cev
        assert "target_id" in cev
        assert "stance" in cev
        assert "issue_type" in cev
        assert "critique" in cev

    # Verify deliberation_end payload
    end_ev = next(ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_END)
    assert end_ev["reason"] == "converged"
    assert end_ev["rounds_used"] == 1
    assert end_ev["open_conflicts"] == 0

    # Verify wire formatting of all custom deliberation events
    delib_yielded = [ev for ev in yielded_events if ev.get("type") in SSE_DELIBERATION_EVENTS]
    for ev in delib_yielded:
        wire = service.format_sse_wire_event(ev)
        assert wire.startswith(f"event: {ev['type']}\n")
        assert wire.endswith("\n\n")


@pytest.mark.asyncio
async def test_deliberation_multiround_revision_streaming():
    """Verify multi-round deliberation streams deliberation_revision events with populated resolved_critiques."""
    mock_model = MockChatModel(model_name="mock-deliberate-multiround")

    constraint = SharedConstraint(
        id="weekly_hours",
        description="Weekly total allowable work units",
        unit="units",
        limit_value=20.0,
        limit_source="user",
    )
    cfg = DeliberationConfig(
        panel_id="panel_multiround_stream",
        shared_constraints=[constraint],
        budget=DeliberationBudget(max_rounds=2),
        critique_mode="per_agent",
    )

    # Round 1 proposals: 8 + 10 = 18 <= 20 budget (no automatic BudgetAuditor conflict)
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Step 1 proposal for 8 units.",
        "resource_claims": {"weekly_hours": 8.0},
        "resource_claim_units": {"weekly_hours": "units"},
    })
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Step 2 proposal for 10 units.",
        "resource_claims": {"weekly_hours": 10.0},
        "resource_claim_units": {"weekly_hours": "units"},
    })
    # Round 1 critiques: Specialist Alpha amends Specialist Beta; Beta endorses Alpha
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "amend",
        "issue_type": "dependency_order",
        "critique": "Step 2 should sequence after step 1 setup.",
        "proposed_resolution": "Adjust step ordering and claim 7 units.",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Step 1 allocation acceptable.",
        "proposed_resolution": "Commit",
    }])

    # Round 2 revised proposal from Specialist Beta only
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 2,
        "scope": "domain_alpha.tasks",
        "summary": "Revised step 2 reducing claim to 7 units.",
        "resource_claims": {"weekly_hours": 7.0},
        "resource_claim_units": {"weekly_hours": "units"},
    })
    # Round 2 critiques: both endorse
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Resolved dependency and 7-unit allocation.",
        "proposed_resolution": "Proceed",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Agreement maintained.",
        "proposed_resolution": "Proceed",
    }])

    engine = DeliberationEngine(model=mock_model, config=cfg)

    async def deliberate_node(s: AgentState) -> Dict[str, Any]:
        return await engine.run(s)

    builder = StateGraph(AgentState)
    builder.add_node("deliberate", deliberate_node)
    builder.add_edge(START, "deliberate")
    builder.add_edge("deliberate", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    plan = ExecutionPlan(
        mode=ExecutionMode.DELIBERATE,
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg,
    )

    yielded_events: List[Dict[str, Any]] = []
    async for event in service.execute_turn(
        thread_id="test_delib_multiround_t2",
        prompt="Schedule multi-round computation",
        execution_plan=plan,
        target_agents=["specialist_alpha", "specialist_beta"],
    ):
        yielded_events.append(event)

    # Verify deliberation_revision event occurred
    rev_events = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_REVISION]
    assert len(rev_events) >= 1

    rev_ev = rev_events[0]
    assert rev_ev["round"] == 2
    assert rev_ev["agent_id"] == "specialist_beta"
    assert rev_ev["scope"] == "domain_alpha.tasks"
    assert "7 units" in rev_ev["summary"]
    # Check that resolved_critiques contains the prior round's critique details
    assert len(rev_ev["resolved_critiques"]) >= 1
    assert any("specialist_alpha" in rc for rc in rev_ev["resolved_critiques"])


@pytest.mark.asyncio
async def test_deliberation_fallback_degradation_emits_deliberation_end():
    """Verify panel degradation when < 2 valid proposals survive emits deliberation_end with reason=single_agent_fallback."""
    mock_model = MockChatModel(model_name="mock-deliberate-degraded")

    cfg = DeliberationConfig(panel_id="panel_degrade_stream")
    # Specialist Alpha succeeds, Specialist Beta fails validation
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Sole surviving proposal.",
    })
    mock_model.queue_response({"malformed": "unparseable garbage"})
    mock_model.queue_response({"malformed": "second attempt failed"})

    engine = DeliberationEngine(model=mock_model, config=cfg)

    async def deliberate_node(s: AgentState) -> Dict[str, Any]:
        return await engine.run(s)

    builder = StateGraph(AgentState)
    builder.add_node("deliberate", deliberate_node)
    builder.add_edge(START, "deliberate")
    builder.add_edge("deliberate", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    plan = ExecutionPlan(
        mode=ExecutionMode.DELIBERATE,
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg,
    )

    yielded_events: List[Dict[str, Any]] = []
    async for event in service.execute_turn(
        thread_id="test_delib_degrade_t3",
        prompt="Schedule task requiring peer review",
        execution_plan=plan,
        target_agents=["specialist_alpha", "specialist_beta"],
    ):
        yielded_events.append(event)

    # Must emit panel_start
    assert any(ev.get("type") == SSE_EVENT_PANEL_START for ev in yielded_events)

    # Must emit deliberation_end with single_agent_fallback
    end_events = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_END]
    assert len(end_events) == 1
    end_ev = end_events[0]
    assert end_ev["reason"] == "single_agent_fallback"
    assert end_ev["rounds_used"] == 1
    assert "specialist_beta" in end_ev["missing_agents"]


@pytest.mark.asyncio
async def test_deliberation_streaming_cross_domain_redaction_end_to_end():
    """Verify end-to-end streaming in a cross-domain panel redacts unauthorized proposal summaries and critiques."""
    mock_model = MockChatModel(model_name="mock-deliberate-cross-stream")

    cfg = DeliberationConfig(panel_id="panel_cross_stream")

    # Specialist Alpha in domain_alpha, Specialist Beta in domain_beta
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Alpha public task proposal.",
        "resource_claims": {"quota": 5.0},
    })
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "domain_beta.tasks",
        "summary": "Beta private confidential proposal details.",
        "resource_claims": {"quota": 8.0},
    })
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Cross-domain critique targeting beta.",
        "proposed_resolution": "Adopt",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Cross-domain critique targeting alpha.",
        "proposed_resolution": "Adopt",
    }])

    engine = DeliberationEngine(model=mock_model, config=cfg)

    async def deliberate_node(s: AgentState) -> Dict[str, Any]:
        return await engine.run(s)

    builder = StateGraph(AgentState)
    builder.add_node("deliberate", deliberate_node)
    builder.add_edge(START, "deliberate")
    builder.add_edge("deliberate", END)
    compiled_graph = builder.compile()

    service = AgentExecutionService(model=mock_model, graph=compiled_graph)

    # Client holds only domain_alpha authorization
    yielded_events: List[Dict[str, Any]] = []
    async for event in service.execute_turn(
        thread_id="test_cross_stream_t4",
        prompt="Execute cross-domain coordination",
        target_agents=["specialist_alpha", "specialist_beta"],
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
        scopes=["domain_alpha.tasks", "domain_beta.tasks"],
        is_cross_domain=True,
    ):
        yielded_events.append(event)

    proposals = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_PROPOSAL]
    assert len(proposals) == 2

    # Alpha's proposal (authorized) has full summary
    alpha_prop = next(p for p in proposals if p["agent_id"] == "specialist_alpha")
    assert alpha_prop["summary"] == "Alpha public task proposal."

    # Beta's proposal (unauthorized scope) has redacted summary
    beta_prop = next(p for p in proposals if p["agent_id"] == "specialist_beta")
    assert beta_prop["summary"] == REDACTED_PLACEHOLDER
    assert beta_prop["resource_claims"] == {"quota": 8.0}
    assert beta_prop["round"] == 1

    # Cross-domain critique targeting beta has redacted critique text
    critiques = [ev for ev in yielded_events if ev.get("type") == SSE_EVENT_DELIBERATION_CRITIQUE]
    for cev in critiques:
        if cev.get("target_scope") == "domain_beta.tasks" or cev.get("reviewer_scope") == "domain_beta.tasks":
            assert cev["critique"] == REDACTED_PLACEHOLDER
            assert cev["stance"] == "endorse"


@pytest.mark.asyncio
async def test_deliberation_resume_turn_forwards_events():
    """Verify execute_resume_turn forwards deliberation events without dropping them."""
    from unittest.mock import MagicMock
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import interrupt

    mock_model = MockChatModel(model_name="mock-deliberate-resume")

    # Build a graph that interrupts on round 1 and emits deliberation events on resumption
    builder = StateGraph(AgentState)

    async def step_node(state: AgentState) -> Dict[str, Any]:
        # Interrupt awaiting approval
        interrupt({"approval_id": "appr_delib_1", "action": "require_approval"})
        from langchain_core.callbacks.manager import adispatch_custom_event
        await adispatch_custom_event(
            SSE_EVENT_PANEL_START,
            {
                "panel_id": "panel_resumed",
                "title": "Resumed Deliberation",
                "agents": ["specialist_alpha"],
                "shared_constraints": [],
            },
        )
        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_END,
            {
                "reason": "converged",
                "rounds_used": 1,
                "open_conflicts": 0,
                "missing_agents": [],
            },
        )
        return {"output": "Resumed deliberation complete"}

    builder.add_node("step", step_node)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)

    cp = MemorySaver()
    compiled_graph = builder.compile(checkpointer=cp)
    service = AgentExecutionService(model=mock_model, graph=compiled_graph, checkpointer=cp)

    class FakeStore:
        def get(self, id):
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {}
            rec.profile_id = "default_profile"
            rec.payload_hash = "fake_hash"
            return rec

    # 1. Initial turn hits interrupt
    async for _ in service.execute_turn(
        thread_id="test_resume_delib_t5",
        prompt="Initial prompt",
    ):
        pass

    # 2. Resumed turn executes post-interrupt step and forwards custom events
    resumed_events: List[Dict[str, Any]] = []
    async for event in service.execute_resume_turn(
        thread_id="test_resume_delib_t5",
        approval_id="appr_delib_1",
        approval_store=FakeStore(),
    ):
        resumed_events.append(event)

    resumed_types = [ev.get("type") for ev in resumed_events]
    assert SSE_EVENT_PANEL_START in resumed_types
    assert SSE_EVENT_DELIBERATION_END in resumed_types

    start_ev = next(ev for ev in resumed_events if ev.get("type") == SSE_EVENT_PANEL_START)
    assert start_ev["panel_id"] == "panel_resumed"

    end_ev = next(ev for ev in resumed_events if ev.get("type") == SSE_EVENT_DELIBERATION_END)
    assert end_ev["reason"] == "converged"


# ============================================================================
# 5. Scope-Filtering and Resumption Security Hardening Tests
# ============================================================================


def test_scope_filter_adversarial_is_cross_domain_false_payload_bypass():
    """Verify untrusted payload key is_cross_domain=False cannot bypass trusted cross-domain context."""
    # 1. Trusted execution_context={'is_cross_domain': True} overrides payload is_cross_domain=False
    payload = {
        "round": 1,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "CONFIDENTIAL_MALICIOUS_BYPASS_ATTEMPT",
        "is_cross_domain": False,
        "resource_claims": {"quota": 10.0},
    }
    filtered = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        payload,
        execution_context={"is_cross_domain": True},
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert filtered["summary"] == REDACTED_PLACEHOLDER
    assert filtered["resource_claims"] == {"quota": 10.0}

    # 2. Scope domain crossing (domain_beta vs domain_alpha) overrides payload cross_domain=False
    payload_cd = {
        "round": 1,
        "agent_id": "specialist_beta",
        "scope": "domain_beta.tasks",
        "summary": "CONFIDENTIAL_CROSS_DOMAIN_BYPASS_ATTEMPT",
        "cross_domain": False,
    }
    filtered_cd = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        payload_cd,
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert filtered_cd["summary"] == REDACTED_PLACEHOLDER


def test_scope_filter_cross_domain_missing_scope_fails_closed():
    """Verify proposal and critique payloads missing scope in cross-domain panels fail closed."""
    # 1. Proposal missing scope in cross-domain panel
    prop_no_scope = {
        "round": 1,
        "agent_id": "specialist_beta",
        "summary": "CONFIDENTIAL_LEAK_WITHOUT_SCOPE",
    }
    res_prop = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        prop_no_scope,
        execution_context={"is_cross_domain": True},
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert res_prop["summary"] == REDACTED_PLACEHOLDER

    # 2. Critique missing scopes in cross-domain panel
    critique_no_scope = {
        "round": 1,
        "reviewer_id": "specialist_alpha",
        "target_id": "specialist_beta",
        "critique": "CONFIDENTIAL_CRITIQUE_WITHOUT_SCOPE",
    }
    res_crit = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_CRITIQUE,
        critique_no_scope,
        execution_context={"is_cross_domain": True},
        client_scope="domain_alpha",
        granted_scopes={"domain_alpha.*"},
    )
    assert res_crit["critique"] == REDACTED_PLACEHOLDER


def test_scope_filter_malformed_scope_types_graceful_handling():
    """Verify filter_deliberation_event handles non-string and non-collection scope types without exceptions."""
    # 1. Malformed scopes sequence (integer instead of list/set)
    res_int_scopes = filter_deliberation_event(
        SSE_EVENT_PANEL_START,
        {"scopes": 12345},
        execution_context={"is_cross_domain": True},
    )
    assert res_int_scopes["scopes"] == 12345

    # 2. Malformed scopes sequence containing non-strings
    res_mixed_scopes = filter_deliberation_event(
        SSE_EVENT_PANEL_START,
        {"scopes": [None, 123, False]},
        execution_context={"is_cross_domain": True},
    )
    assert res_mixed_scopes["scopes"] == [None, 123, False]

    # 3. Non-string reviewer_scope and target_scope
    res_bad_critique = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_CRITIQUE,
        {
            "reviewer_scope": 123,
            "target_scope": 456,
            "critique": "Confidential critique with bad scope types",
        },
        execution_context={"is_cross_domain": True},
    )
    assert res_bad_critique["critique"] == REDACTED_PLACEHOLDER

    # 4. Non-string proposal scope
    res_bad_prop = filter_deliberation_event(
        SSE_EVENT_DELIBERATION_PROPOSAL,
        {
            "scope": 999,
            "summary": "Confidential proposal with integer scope",
        },
        execution_context={"is_cross_domain": True},
    )
    assert res_bad_prop["summary"] == REDACTED_PLACEHOLDER


@pytest.mark.asyncio
async def test_deliberation_resume_turn_cross_domain_execution_context_redaction():
    """Verify execute_resume_turn applies scope filtering when execution_context is provided."""
    from unittest.mock import MagicMock
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import interrupt

    mock_model = MockChatModel(model_name="mock-resume-cross-domain")
    builder = StateGraph(AgentState)

    async def step_node(state: AgentState) -> Dict[str, Any]:
        interrupt({"approval_id": "appr_cross_res_1", "action": "require_approval"})
        from langchain_core.callbacks.manager import adispatch_custom_event

        await adispatch_custom_event(
            SSE_EVENT_DELIBERATION_PROPOSAL,
            {
                "round": 2,
                "agent_id": "specialist_beta",
                "scope": "domain_beta.tasks",
                "summary": "Confidential resume proposal text.",
                "resource_claims": {"units": 5.0},
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

    class FakeStore:
        def get(self, id):
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {}
            rec.profile_id = "default_profile"
            rec.payload_hash = "hash_1"
            return rec

    async for _ in service.execute_turn(thread_id="test_resume_sec_t1", prompt="Initial"):
        pass

    resumed_events = []
    async for ev in service.execute_resume_turn(
        thread_id="test_resume_sec_t1",
        approval_id="appr_cross_res_1",
        approval_store=FakeStore(),
        execution_context={
            "is_cross_domain": True,
            "scope": "domain_alpha",
            "granted_scopes": {"domain_alpha.*"},
            "scopes": ["domain_alpha.tasks", "domain_beta.tasks"],
        },
    ):
        resumed_events.append(ev)

    proposals = [e for e in resumed_events if e.get("type") == SSE_EVENT_DELIBERATION_PROPOSAL]
    assert len(proposals) == 1
    assert proposals[0]["summary"] == REDACTED_PLACEHOLDER
    assert proposals[0]["resource_claims"] == {"units": 5.0}
    assert proposals[0]["tainted"] is False

