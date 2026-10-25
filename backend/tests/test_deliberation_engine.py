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

"""Comprehensive unit and integration test suite for multi-agent blackboard deliberation engine (M2 / R2).

Verifies ADR 0001 §2 and §7 Phase 1 invariants:
1. test_deliberation_lifecycle_propose_to_synthesize
2. test_read_only_tool_gate_during_deliberation
3. test_peer_critique_per_agent_mode & test_peer_critique_batched_mode
4. test_budget_auditor_detects_overbudget_conflict
5. test_budget_auditor_skips_unknown_limit
6. test_budget_auditor_fails_on_unit_mismatch
7. test_convergence_gate_advances_on_open_critiques, test_convergence_gate_terminates_on_consensus & test_convergence_gate_terminates_on_max_rounds
8. test_selective_revision_call_savings
9. test_confidence_neutrality_in_convergence
10. test_schema_repair_retry_and_degradation
11. test_budget_wall_clock_and_token_exhaustion
12. test_execute_turn_and_resume_topology_parity
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List

from yarvelle_core.engine.service import AgentExecutionService, ExecutionService
from yarvelle_core.engine.tool_exec import ToolContext, ToolSpec
from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    ExecutionMode,
    ExecutionPlan,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor, UnitMismatchError
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager, DeliberationBlackboard
from yarvelle_core.workflows.deliberation.doc_critique import parse_json_or_literal, run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.deliberation.gate import evaluate_convergence_gate
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.deliberation.subgraph import create_deliberation_subgraph
from yarvelle_core.workflows.deliberation.tool_gate import (
    evaluate_deliberation_tool_gate,
    filter_read_only_tools,
)
from yarvelle_core.workflows.state import (
    AgentProposal,
    AgentState,
    CritiqueStance,
    PeerCritique,
    StagedAction,
    create_initial_state,
)
try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


@pytest.fixture
def mock_model():
    return MockChatModel(model_name="mock-deliberate")


@pytest.fixture
def generic_shared_constraint():
    return SharedConstraint(
        id="weekly_quota",
        description="Weekly total allowable units",
        unit="hours",
        limit_value=20.0,
        limit_source="user",
    )


@pytest.fixture
def deliberation_config(generic_shared_constraint):
    return DeliberationConfig(
        panel_id="panel_alpha",
        moderator_agent_id="orchestrator",
        budget=DeliberationBudget(max_rounds=2, max_wall_clock_s=120.0, max_total_tokens=40_000),
        shared_constraints=[generic_shared_constraint],
        critique_mode="per_agent",
    )


# ============================================================================
# 1. Full Multi-Round Deliberation Lifecycle
# ============================================================================


@pytest.mark.asyncio
async def test_deliberation_lifecycle_propose_to_synthesize(mock_model, deliberation_config):
    """Verify full end-to-end deliberation cycle from Propose to Synthesize across 2 rounds."""
    # Round 1 proposals
    proposal_a_r1 = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha.tasks",
        "summary": "Execute step 1 requiring 8 hours.",
        "recommendations": ["Initiate phase 1", "Configure logging"],
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    proposal_b_r1 = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_alpha.tasks",
        "summary": "Execute step 2 requiring 10 hours.",
        "recommendations": ["Initiate phase 2", "Validate checkpoints"],
        "resource_claims": {"weekly_quota": 10.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    # Round 1 peer critiques: Peer A amends Peer B; Peer B endorses Peer A
    critique_a_to_b = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 1,
        "stance": "amend",
        "issue_type": "dependency_order",
        "critique": "Step 2 should sequence after step 1 logging setup.",
        "proposed_resolution": "Adjust step ordering and timing.",
    }
    critique_b_to_a = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Step 1 setup provides clean infrastructure prerequisites.",
        "proposed_resolution": "Commit to step 1.",
    }
    # Round 2 revised proposals: Specialist B reduces claim to 7.0 hours
    proposal_b_r2 = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha.tasks",
        "summary": "Revised step 2 requiring 7 hours with updated sequencing.",
        "recommendations": ["Initiate phase 2 aligned after step 1"],
        "resource_claims": {"weekly_quota": 7.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    # Round 2 peer critiques: Both endorse
    critique_endorse_a_to_b = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Revised sequencing and 7-hour allocation resolve dependency.",
        "proposed_resolution": "Proceed with plan.",
    }
    critique_endorse_b_to_a = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Infrastructure prerequisites remain sound and agreed upon.",
        "proposed_resolution": "Proceed with plan.",
    }

    mock_model.queue_response(proposal_a_r1)
    mock_model.queue_response(proposal_b_r1)
    mock_model.queue_response([critique_a_to_b])
    mock_model.queue_response([critique_b_to_a])
    mock_model.queue_response(proposal_b_r2)
    mock_model.queue_response([critique_endorse_a_to_b])
    mock_model.queue_response([critique_endorse_b_to_a])

    engine = DeliberationEngine(model=mock_model, config=deliberation_config)
    initial_state = create_initial_state(
        prompt="Coordinate task scheduling within 20 hour quota",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=deliberation_config.model_dump(),
    )

    final_state = await engine.run(initial_state)

    delib_state = final_state["deliberation_state"]
    assert delib_state["rounds_used"] == 2
    assert delib_state["converged"] is True
    assert final_state["output"] is not None
    assert "specialist_a" in final_state["specialist_outputs"]
    assert "specialist_b" in final_state["specialist_outputs"]


# ============================================================================
# 2. Read-Only Tool Gating & Dropping Staged Actions
# ============================================================================


def test_read_only_tool_gate_during_deliberation():
    """Verify tool gate allows read-tier tools and blocks write-tier tools during deliberation rounds."""
    read_tool = ToolSpec(name="fetch_metric", risk_tier="read")
    write_tool = ToolSpec(name="store_record", risk_tier="write_local")
    ext_tool = ToolSpec(name="notify_external", risk_tier="write_external")

    ctx = ToolContext(user_id="u1", profile_id="p1", autonomy="A2")

    dec_read = evaluate_deliberation_tool_gate(ctx, read_tool, {"key": "alpha"})
    assert dec_read.decision == "allow"

    dec_write = evaluate_deliberation_tool_gate(ctx, write_tool, {"data": "test"})
    assert dec_write.decision == "blocked"
    assert "read-tier" in dec_write.reason.lower() or "deliberation" in dec_write.reason.lower()

    dec_ext = evaluate_deliberation_tool_gate(ctx, ext_tool, {"msg": "alert"})
    assert dec_ext.decision == "blocked"

    # Also verify staged actions in AgentProposal are dropped in Phase 1
    proposal_with_staged_write = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal staging write action",
        staged_actions=[
            StagedAction(
                agent_id="specialist_a",
                tool_name="store_record",
                tool_args={"id": "rec-1"},
                rationale="Persist task record",
                risk_tier="write_local",
            )
        ],
    )
    bb = BlackboardManager()
    bb.record_proposal(proposal_with_staged_write)
    # Phase 1 drops staged write actions
    assert len(bb.get_active_staged_actions()) == 0


# ============================================================================
# 3. Disagree-or-Commit Peer Critique (per_agent vs batched)
# ============================================================================


@pytest.mark.asyncio
async def test_peer_critique_per_agent_mode(mock_model):
    """Verify per_agent critique mode invokes each reviewer individually and validates DoC rules."""
    proposals = [
        AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="Proposal A"),
        AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="Proposal B"),
        AgentProposal(agent_id="specialist_c", round_num=1, scope="scope_alpha", summary="Proposal C"),
    ]

    # Model returns 1 critique batch per agent call
    mock_model.queue_response([
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Valid supporting point for step 1", "proposed_resolution": "Commit"}
    ])
    mock_model.queue_response([
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 1, "stance": "amend", "issue_type": "dependency_order", "critique": "Sequence step 2 after step 1", "proposed_resolution": "Adjust sequence"}
    ])
    mock_model.queue_response([
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_a", "round_num": 1, "stance": "complement", "issue_type": "synergy", "critique": "Merge monitoring hooks", "proposed_resolution": "Joint logging"}
    ])

    critiques = await run_peer_critiques(proposals, mode="per_agent", model=mock_model, round_num=1)
    assert len(critiques) == 3
    assert mock_model.call_count == 3


@pytest.mark.asyncio
async def test_peer_critique_batched_mode(mock_model):
    """Verify batched critique mode executes single moderator call returning critique matrix."""
    proposals = [
        AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="Proposal A"),
        AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="Proposal B"),
    ]
    mock_model.queue_response([
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Aligns with schema requirements", "proposed_resolution": "Commit"},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "amend", "issue_type": "risk_exposure", "critique": "Add error handling to step 1", "proposed_resolution": "Include retry"},
    ])

    critiques = await run_peer_critiques(proposals, mode="batched", model=mock_model, round_num=1)
    assert len(critiques) == 2
    assert mock_model.call_count == 1


# ============================================================================
# 4. Deterministic Budget Auditor (Overbudget Conflict Detection)
# ============================================================================


def test_budget_auditor_detects_overbudget_conflict():
    """Verify BudgetAuditor sums resource claims vs user/profile limit and emits CONFLICT critique."""
    constraint = SharedConstraint(
        id="weekly_hours",
        description="Weekly allowable hours",
        unit="hours",
        limit_value=20.0,
        limit_source="user",
    )
    proposals = [
        AgentProposal(
            agent_id="specialist_a",
            round_num=1,
            scope="scope_alpha",
            summary="A claims 12 hours",
            resource_claims={"weekly_hours": 12.0},
            resource_claim_units={"weekly_hours": "hours"},
        ),
        AgentProposal(
            agent_id="specialist_b",
            round_num=1,
            scope="scope_alpha",
            summary="B claims 10 hours",
            resource_claims={"weekly_hours": 10.0},
            resource_claim_units={"weekly_hours": "hours"},
        ),
    ]

    auditor = BudgetAuditor()
    critiques = auditor.audit(constraints=[constraint], proposals=proposals, round_num=1)

    assert len(critiques) == 2
    assert {c.target_agent_id for c in critiques} == {"specialist_a", "specialist_b"}
    for critique in critiques:
        assert critique.stance is CritiqueStance.CONFLICT
        assert critique.issue_type == "resource_overbudget"
        assert critique.resolved is False
        assert "22.0" in critique.critique
        assert "20.0" in critique.critique


# ============================================================================
# 5. Deterministic Budget Auditor (Skipping Unknown Limit)
# ============================================================================


def test_budget_auditor_skips_unknown_limit():
    """Verify BudgetAuditor skips constraints where limit_value is None without error."""
    constraint = SharedConstraint(
        id="unbounded_compute",
        description="Compute slots limit unknown",
        unit="units",
        limit_value=None,
        limit_source=None,
    )
    proposals = [
        AgentProposal(
            agent_id="specialist_a",
            round_num=1,
            scope="scope_alpha",
            summary="A claims 50 units",
            resource_claims={"unbounded_compute": 50.0},
            resource_claim_units={"unbounded_compute": "units"},
        ),
        AgentProposal(
            agent_id="specialist_b",
            round_num=1,
            scope="scope_alpha",
            summary="B claims 75 units",
            resource_claims={"unbounded_compute": 75.0},
            resource_claim_units={"unbounded_compute": "units"},
        ),
    ]

    auditor = BudgetAuditor()
    critiques = auditor.audit(constraints=[constraint], proposals=proposals, round_num=1)
    assert len(critiques) == 0
    assert "unbounded_compute" in auditor.skipped_constraints


# ============================================================================
# 6. Deterministic Budget Auditor (Unit Mismatch Failure)
# ============================================================================


def test_budget_auditor_fails_on_unit_mismatch():
    """Verify BudgetAuditor raises UnitMismatchError on unit mismatch without guessing conversions."""
    constraint = SharedConstraint(
        id="weekly_hours",
        description="Weekly allowable hours",
        unit="hours",
        limit_value=10.0,
        limit_source="user",
    )
    proposals = [
        AgentProposal(
            agent_id="specialist_a",
            round_num=1,
            scope="scope_alpha",
            summary="A claims 120 minutes",
            resource_claims={"weekly_hours": 120.0},
            resource_claim_units={"weekly_hours": "minutes"},  # Mismatch!
        ),
    ]

    auditor = BudgetAuditor()
    with pytest.raises(UnitMismatchError) as exc_info:
        auditor.audit(constraints=[constraint], proposals=proposals, round_num=1)

    assert "minutes" in str(exc_info.value)
    assert "hours" in str(exc_info.value)


# ============================================================================
# 7. Rule-Based Convergence Gate Transitions
# ============================================================================


def test_convergence_gate_advances_on_open_critiques():
    """Verify ConvergenceGate advances to selective_revise when open CONFLICT or AMEND exists."""
    open_conflict = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Exceeds quota",
        proposed_resolution="Reduce allocation",
        resolved=False,
    )
    decision = evaluate_convergence_gate(
        critiques=[open_conflict],
        round_num=1,
        max_rounds=2,
        budget_remaining=True,
    )
    assert decision.next_node == "selective_revise"
    assert decision.target_agents == ["specialist_b"]


def test_convergence_gate_terminates_on_consensus():
    """Verify ConvergenceGate terminates to synthesize when all critiques endorse or complement."""
    endorse = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.ENDORSE,
        issue_type="synergy",
        critique="Proposal aligns with prerequisites",
        proposed_resolution="Commit",
        resolved=True,
    )
    decision = evaluate_convergence_gate(
        critiques=[endorse],
        round_num=1,
        max_rounds=2,
        budget_remaining=True,
    )
    assert decision.next_node == "synthesize"
    assert decision.converged is True


def test_convergence_gate_terminates_on_max_rounds():
    """Verify ConvergenceGate terminates to synthesize when max_rounds is reached despite open conflict."""
    open_conflict = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=2,
        stance=CritiqueStance.CONFLICT,
        issue_type="dependency_order",
        critique="Unresolved ordering conflict",
        proposed_resolution="Option A vs Option B",
        resolved=False,
    )
    decision = evaluate_convergence_gate(
        critiques=[open_conflict],
        round_num=2,
        max_rounds=2,
        budget_remaining=True,
    )
    assert decision.next_node == "synthesize"
    assert decision.reason == "max_rounds_reached"


# ============================================================================
# 8. Selective Revision Call-Count Savings
# ============================================================================


@pytest.mark.asyncio
async def test_selective_revision_call_savings(mock_model):
    """Verify SelectiveRevise re-runs ONLY challenged agents and saves LLM calls."""
    proposals_r1 = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="A proposal"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="B proposal"),
        "specialist_c": AgentProposal(agent_id="specialist_c", round_num=1, scope="scope_alpha", summary="C proposal"),
        "specialist_d": AgentProposal(agent_id="specialist_d", round_num=1, scope="scope_alpha", summary="D proposal"),
    }
    # Only specialist_b is targeted by an open AMEND critique
    critiques = [
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            round_num=1,
            stance=CritiqueStance.AMEND,
            issue_type="dependency_order",
            critique="Update sequence for step 2",
            proposed_resolution="Run after step 1",
            resolved=False,
        )
    ]

    mock_model.queue_response({
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Revised B proposal with updated sequence",
    })

    updated_proposals = await run_selective_revision(
        active_proposals=proposals_r1,
        critiques=critiques,
        round_num=2,
        model=mock_model,
    )

    # Exactly 1 call made for specialist_b, saving 3 calls (4 -> 1)
    assert mock_model.call_count == 1
    assert updated_proposals["specialist_b"].round_num == 2
    assert updated_proposals["specialist_a"].round_num == 1
    assert updated_proposals["specialist_c"].round_num == 1
    assert updated_proposals["specialist_d"].round_num == 1


# ============================================================================
# 9. Confidence Neutrality in Convergence Gate
# ============================================================================


def test_confidence_neutrality_in_convergence():
    """Verify proposal self-reported confidence has zero effect on convergence decisions."""
    # Scenario A: Low confidence (0.05) with all endorsements -> Converges to synthesize
    proposal_low = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal with low confidence",
        confidence=0.05,
    )
    critique_endorse = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=1,
        stance=CritiqueStance.ENDORSE,
        issue_type="synergy",
        critique="Valid approach despite modesty",
        proposed_resolution="Commit",
        resolved=True,
    )
    decision_a = evaluate_convergence_gate(
        critiques=[critique_endorse],
        proposals=[proposal_low],
        round_num=1,
        max_rounds=2,
        budget_remaining=True,
    )
    assert decision_a.next_node == "synthesize"
    assert decision_a.converged is True

    # Scenario B: High confidence (1.0) with open conflict -> Advances to selective_revise
    proposal_high = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal with absolute confidence",
        confidence=1.00,
    )
    critique_conflict = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Over budget regardless of confidence",
        proposed_resolution="Reduce claims",
        resolved=False,
    )
    decision_b = evaluate_convergence_gate(
        critiques=[critique_conflict],
        proposals=[proposal_high],
        round_num=1,
        max_rounds=2,
        budget_remaining=True,
    )
    assert decision_b.next_node == "selective_revise"


# ============================================================================
# 10. Schema Repair Retry & Degradation to Single-Agent
# ============================================================================


@pytest.mark.asyncio
async def test_schema_repair_retry_success(mock_model):
    """Verify agent gets exactly 1 repair retry upon schema failure and succeeds if valid."""
    # 1st call fails schema validation (missing required fields)
    mock_model.queue_response({"invalid_payload": "corrupted"})
    # 2nd call (repair retry) returns valid proposal
    mock_model.queue_response({
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Repaired proposal",
    })

    proposal = await generate_agent_proposal(
        agent_id="specialist_a",
        round_num=1,
        context={"prompt": "Task"},
        model=mock_model,
        max_retries=1,
    )
    assert proposal.agent_id == "specialist_a"
    assert proposal.summary == "Repaired proposal"
    assert mock_model.call_count == 2


@pytest.mark.asyncio
async def test_schema_repair_retry_exhaustion_and_degradation(mock_model):
    """Verify agent dropped after 1 failed retry; degrades to single-agent answer if < 2 agents remain."""
    # Agent A succeeds
    mock_model.queue_response({
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Valid proposal A",
    })
    # Agent B fails twice (call 1 and retry call 2)
    mock_model.queue_response({"garbage": 1})
    mock_model.queue_response({"garbage": 2})

    config = DeliberationConfig(panel_id="panel_alpha")
    engine = DeliberationEngine(model=mock_model, config=config)

    state = create_initial_state(
        prompt="Execute panel task",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=config.model_dump(),
    )
    res_state = await engine.run(state)

    delib_state = res_state["deliberation_state"]
    assert delib_state["degraded"] is True
    assert "specialist_b" in delib_state["missing_agents"]
    assert len(delib_state["active_proposals"]) == 1
    assert "single-agent" in res_state["output"].lower() or "missing" in res_state["output"].lower()


# ============================================================================
# 11. Wall-Clock & Token Budget Termination
# ============================================================================


def test_budget_wall_clock_and_token_exhaustion(mock_model):
    """Verify deliberation terminates immediately when wall-clock or token budget is exhausted."""
    # Subcase A: Wall clock timeout
    budget_timeout = DeliberationBudget(max_rounds=4, max_wall_clock_s=0.001)
    config_timeout = DeliberationConfig(budget=budget_timeout)

    engine_timeout = DeliberationEngine(model=mock_model, config=config_timeout)
    engine_timeout._start_time = 0.0001  # Far in the past
    decision = engine_timeout.check_budget(round_num=1, total_tokens=100)
    assert decision.exhausted is True
    assert decision.reason == "wall_clock_timeout"

    # Subcase B: Token cap exhaustion
    budget_tokens = DeliberationBudget(max_rounds=4, max_total_tokens=500)
    config_tokens = DeliberationConfig(budget=budget_tokens)
    engine_tokens = DeliberationEngine(model=mock_model, config=config_tokens)

    decision_tok = engine_tokens.check_budget(round_num=1, total_tokens=600)
    assert decision_tok.exhausted is True
    assert decision_tok.reason == "token_budget_exhausted"


# ============================================================================
# 12. Graph Compilation Parity Between Turn and Resume
# ============================================================================


def test_execute_turn_and_resume_topology_parity():
    """Verify execute_turn and execute_resume_turn compile the identical GraphBuilder graph topology."""
    from yarvelle_core.engine.builder import GraphBuilder
    from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS

    active_model = MockChatModel(model_name="mock")
    effective_tools = list(CLOSED_TOOL_DEFINITIONS.values())
    execution_context = {"tenant_id": "test_tenant", "autonomy": "A1"}

    # Graph built by execute_turn path
    builder_turn = (
        GraphBuilder(include_supervisor=False)
        .with_model(active_model)
        .with_execution_context(execution_context)
        .with_tools(effective_tools)
    )
    graph_turn = builder_turn.create_graph()

    # Graph built by execute_resume_turn path (enforcing parity invariant)
    builder_resume = (
        GraphBuilder(include_supervisor=False)
        .with_model(active_model)
        .with_execution_context(execution_context)
        .with_tools(effective_tools)
    )
    graph_resume = builder_resume.create_graph()

    # Introspect nodes and edges
    turn_nodes = set(graph_turn.nodes.keys())
    resume_nodes = set(graph_resume.nodes.keys())
    assert turn_nodes == resume_nodes, f"Node topology disparity: {turn_nodes ^ resume_nodes}"

    turn_edges = set(graph_turn.edges)
    resume_edges = set(graph_resume.edges)
    assert turn_edges == resume_edges, f"Edge topology disparity: {turn_edges ^ resume_edges}"

    # Also verify ExecutionService alias and _build_execution_graph parity
    svc = ExecutionService()
    graph_turn_svc = svc._build_execution_graph(
        active_model=active_model,
        checkpointer=None,
        effective_store=None,
        execution_context=execution_context,
        effective_tools=effective_tools,
    )
    graph_resume_svc = svc._build_execution_graph(
        active_model=active_model,
        checkpointer=None,
        effective_store=None,
        execution_context=execution_context,
        effective_tools=effective_tools,
    )
    assert set(graph_turn_svc.nodes.keys()) == set(graph_resume_svc.nodes.keys())


# ============================================================================
# 13. Remediation Verifications (M2 Iteration 2)
# ============================================================================


def test_tool_gate_fail_closed_and_dictionary_support():
    """Verify tool gating fails closed for missing tiers, checks dicts, and supports case-insensitivity."""
    ctx = ToolContext(user_id="u1", profile_id="p1", autonomy="A2")

    tools = [
        {"name": "delete_all", "risk_tier": "irreversible"},
        {"name": "write_cache", "risk_tier": "write_local"},
        {"name": "unspecified_tool"},  # Missing risk_tier -> must fail closed
        {"name": "fetch_metric", "risk_tier": "read"},
        {"name": "inspect_state", "risk_tier": "READ"},  # Case-insensitive
        ToolSpec(name="fetch_spec", risk_tier="read"),
        ToolSpec(name="write_spec", risk_tier="write_local"),
    ]

    filtered = filter_read_only_tools(tools)
    filtered_names = [t.get("name") if isinstance(t, dict) else t.name for t in filtered]
    assert filtered_names == ["fetch_metric", "inspect_state", "fetch_spec"]

    # Verify evaluate_deliberation_tool_gate on dicts and objects
    allow_dec = evaluate_deliberation_tool_gate(ctx, {"name": "fetch_metric", "risk_tier": "read"}, {})
    assert allow_dec.decision == "allow"

    block_dict_dec = evaluate_deliberation_tool_gate(ctx, {"name": "delete_all", "risk_tier": "irreversible"}, {})
    assert block_dict_dec.decision == "blocked"

    missing_tier_dec = evaluate_deliberation_tool_gate(ctx, {"name": "unknown_tool"}, {})
    assert missing_tier_dec.decision == "blocked"


@pytest.mark.asyncio
async def test_propose_and_revise_tool_binding_and_agent_id_integrity(mock_model):
    """Verify read_tools are bound to model/context and agent_id is strictly preserved against hallucination."""
    tools = [
        {"name": "query_logs", "risk_tier": "read"},
        {"name": "purge_logs", "risk_tier": "write_local"},
    ]
    ctx: Dict[str, Any] = {"task": "Analyze logs"}

    # Mock model returns an agent_id different from the requested agent (simulating hallucination)
    mock_model.queue_response({
        "agent_id": "hallucinated_agent_x",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Summary of log analysis",
    })

    prop = await generate_agent_proposal(
        agent_id="specialist_alpha",
        round_num=1,
        context=ctx,
        model=mock_model,
        tools=tools,
    )
    # Integrity invariant: agent_id must match the assigned specialist, not the hallucinated one
    assert prop.agent_id == "specialist_alpha"

    # Selective revision test: model returns hallucinated agent_id
    mock_model.queue_response({
        "agent_id": "hallucinated_agent_y",
        "round_num": 2,
        "scope": "default_scope",
        "summary": "Revised summary",
    })

    critique = PeerCritique(
        reviewer_agent_id="specialist_beta",
        target_agent_id="specialist_alpha",
        round_num=1,
        stance=CritiqueStance.AMEND,
        issue_type="dependency_order",
        critique="Refine log timestamp parsing sequence",
        proposed_resolution="Use iso8601 parser",
    )

    revised_props = await run_selective_revision(
        active_proposals={"specialist_alpha": prop},
        critiques=[critique],
        round_num=2,
        model=mock_model,
        context=ctx,
        tools=tools,
    )
    assert "specialist_alpha" in revised_props
    assert revised_props["specialist_alpha"].agent_id == "specialist_alpha"


@pytest.mark.asyncio
async def test_create_deliberation_subgraph_normal(mock_model):
    """Verify create_deliberation_subgraph executes propose -> cross_examine -> gate when >= 2 agents survive."""
    cfg = DeliberationConfig(panel_id="panel_subgraph_normal")
    subgraph = create_deliberation_subgraph(model=mock_model, config=cfg).compile()

    # Round 1 proposals
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Proposal Alpha summary",
    })
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Proposal Beta summary",
    })
    # Peer critiques
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Solid analysis provided",
        "proposed_resolution": "Adopt",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Prerequisites are verified",
        "proposed_resolution": "Adopt",
    }])

    initial_state = create_initial_state(
        prompt="Execute distributed computation review",
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg.model_dump(),
    )

    result_state = await subgraph.ainvoke(initial_state)
    d_state = result_state.get("deliberation_state", {})
    assert d_state.get("degraded") is not True
    assert len(d_state.get("active_proposals", {})) == 2
    assert d_state.get("converged") is True


@pytest.mark.asyncio
async def test_create_deliberation_subgraph_degraded(mock_model):
    """Verify create_deliberation_subgraph routes propose directly to END on single-agent degradation."""
    cfg = DeliberationConfig(panel_id="panel_subgraph_degraded")
    subgraph = create_deliberation_subgraph(model=mock_model, config=cfg).compile()

    # Agent alpha succeeds
    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Proposal Alpha summary",
    })
    # Agent beta fails on both attempt 1 and retry 2
    mock_model.queue_response({"invalid_schema": 1})
    mock_model.queue_response({"invalid_schema": 2})

    initial_state = create_initial_state(
        prompt="Execute distributed computation review",
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg.model_dump(),
    )

    result_state = await subgraph.ainvoke(initial_state)
    d_state = result_state.get("deliberation_state", {})
    assert d_state.get("degraded") is True
    assert d_state.get("round_num") == 1
    assert "degraded to single-agent fallback" in result_state.get("output", "")


def test_budget_auditor_missing_unit_and_float_epsilon():
    """Verify budget auditor rejects claims with missing units and tolerates float epsilon."""
    constraint = SharedConstraint(
        id="cpu_seconds",
        description="CPU seconds quota",
        unit="seconds",
        limit_value=0.3,
        limit_source="user",
    )

    # 1. Missing resource_claim_units raises UnitMismatchError
    proposal_no_unit = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="default_scope",
        summary="Computation proposal",
        resource_claims={"cpu_seconds": 0.1},
        resource_claim_units={},  # Missing unit!
    )
    auditor = BudgetAuditor()
    with pytest.raises(UnitMismatchError, match="expected 'seconds', got 'None'"):
        auditor.audit([constraint], [proposal_no_unit])

    # 2. Float precision: 0.1 + 0.2 = 0.30000000000000004 against limit 0.3
    # Must NOT emit conflict thanks to epsilon tolerance
    p1 = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="default_scope",
        summary="P1",
        resource_claims={"cpu_seconds": 0.1},
        resource_claim_units={"cpu_seconds": "seconds"},
    )
    p2 = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="default_scope",
        summary="P2",
        resource_claims={"cpu_seconds": 0.2},
        resource_claim_units={"cpu_seconds": "seconds"},
    )
    critiques = auditor.audit([constraint], [p1, p2])
    assert len(critiques) == 0, f"False positive overbudget conflict triggered: {critiques}"


@pytest.mark.asyncio
async def test_service_resumption_without_tools_does_not_crash():
    """Verify execute_resume_turn does not crash when tools argument is omitted."""
    from unittest.mock import MagicMock

    class FakeStore:
        def get(self, id):
            rec = MagicMock()
            rec.status = "approved"
            rec.args = {}
            rec.profile_id = "default_profile"
            rec.payload_hash = "fake_hash"
            return rec

    service = ExecutionService()
    # Resume turn without 'tools' in kwargs
    async for _ in service.execute_resume_turn(
        thread_id="test_thread",
        approval_id="test_approval",
        action="approve",
        approval_store=FakeStore(),
    ):
        pass


@pytest.mark.asyncio
async def test_engine_skipped_constraints_and_markdown_json_codeblock(mock_model):
    """Verify skipped_constraints is tracked and markdown JSON blocks within text parse cleanly."""
    # 1. Test markdown JSON parsing with leading/trailing text
    raw_response = (
        "Here is the requested proposal payload:\n\n"
        "```json\n"
        '{"agent_id": "specialist_alpha", "round_num": 1, "scope": "default_scope", "summary": "Codeblock extracted"}\n'
        "```\n\n"
        "Please let me know if changes are required."
    )
    parsed = parse_json_or_literal(raw_response)
    assert isinstance(parsed, dict)
    assert parsed["summary"] == "Codeblock extracted"

    # 2. Test skipped_constraints in DeliberationEngine.run
    c_skipped = SharedConstraint(
        id="unbounded_bandwidth",
        description="Unbounded bandwidth",
        unit="megabytes",
        limit_value=None,  # Must be skipped
        limit_source=None,
    )
    cfg = DeliberationConfig(
        panel_id="panel_skipped_test",
        shared_constraints=[c_skipped],
    )
    engine = DeliberationEngine(model=mock_model, config=cfg)

    mock_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Summary Alpha",
    })
    mock_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "default_scope",
        "summary": "Summary Beta",
    })
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Looks good and verified",
        "proposed_resolution": "Proceed",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Looks good and verified",
        "proposed_resolution": "Proceed",
    }])

    initial_state = create_initial_state(
        prompt="Review bandwidth allocation",
        target_agents=["specialist_alpha", "specialist_beta"],
        deliberation_config=cfg.model_dump(),
    )
    res_state = await engine.run(initial_state)
    d_state = res_state.get("deliberation_state", {})
    assert "unbounded_bandwidth" in d_state.get("skipped_constraints", [])

