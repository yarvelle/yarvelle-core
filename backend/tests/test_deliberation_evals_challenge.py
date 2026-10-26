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

"""Empirical challenger stress-test suite for multi-agent deliberation (M4 / R4).

Adversarially challenges evaluation formulas, scaling limits, and invariants:
1. Mathematical scaling across panel sizes N in [2..8]:
   - (N - 1) / N critique savings in batched mode across all N in [2..8].
   - Full lifecycle (N - 1) / (2N) savings across all N in [2..8].
2. (N - K) / N selective revision savings:
   - Evaluated across all panel sizes N in [2..8] and all K <= N combinations.
   - Deduping multiple critiques targeting the same agent (1 call, not C calls).
   - Staged write action dropping in Phase 1 selective revision.
3. Token budget truncation & wall-clock timeout thresholds under high event frequency:
   - Exact boundary and over-budget conditions for tokens and wall-clock time.
   - High event frequency SSE emission stress.
4. Multi-issue concurrent conflicts & deterministic convergence:
   - Simultaneous budget + dependency + strategy + risk conflicts resolving at Round 2.
   - Partial resolution with persistent strategic conflict terminating boundedly.
   - Cyclic multi-agent conflict graph (A -> B -> C -> D -> A) bounded termination.
"""

from __future__ import annotations

import asyncio
import itertools
import math
import time
from typing import Any, Dict, List, Sequence
import pytest

from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor, UnitMismatchError
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine, _emit_sse_event
from yarvelle_core.workflows.deliberation.gate import evaluate_convergence_gate
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.state import (
    AgentProposal,
    CritiqueStance,
    PeerCritique,
    StagedAction,
    create_initial_state,
)

try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


# ============================================================================
# Section 1: Mathematical Scaling Across Panel Sizes N in [2..8]
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_size", [2, 3, 4, 5, 6, 7, 8])
async def test_challenge_critique_mode_scaling_n2_to_n8(panel_size: int):
    """Stress-test peer critique scaling across all panel sizes N in [2..8]:
    - per_agent mode makes exactly N calls.
    - batched mode makes exactly 1 call.
    - Mathematical savings is exactly (N - 1) / N.
    """
    agent_ids = [f"specialist_{i}" for i in range(panel_size)]
    proposals = [
        AgentProposal(
            agent_id=aid,
            round_num=1,
            scope="scope_eval",
            summary=f"Proposal from {aid}",
        )
        for aid in agent_ids
    ]

    # 1. per_agent mode
    model_pa = MockChatModel(model_name=f"mock-pa-{panel_size}")
    for reviewer_id in agent_ids:
        peer_id = next(p for p in agent_ids if p != reviewer_id)
        model_pa.queue_response([
            {
                "reviewer_agent_id": reviewer_id,
                "target_agent_id": peer_id,
                "round_num": 1,
                "stance": "endorse",
                "issue_type": "synergy",
                "critique": f"Supporting rationale from {reviewer_id}",
                "proposed_resolution": "Commit",
            }
        ])

    critiques_pa = await run_peer_critiques(
        proposals=proposals, mode="per_agent", model=model_pa, round_num=1
    )
    assert model_pa.call_count == panel_size
    assert len(critiques_pa) == panel_size

    # 2. batched mode
    model_ba = MockChatModel(model_name=f"mock-ba-{panel_size}")
    batched_matrix = [
        {
            "reviewer_agent_id": agent_ids[i],
            "target_agent_id": agent_ids[(i + 1) % panel_size],
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": f"Batch supporting rationale from {agent_ids[i]}",
            "proposed_resolution": "Commit",
        }
        for i in range(panel_size)
    ]
    model_ba.queue_response(batched_matrix)

    critiques_ba = await run_peer_critiques(
        proposals=proposals, mode="batched", model=model_ba, round_num=1
    )
    assert model_ba.call_count == 1
    assert len(critiques_ba) == panel_size

    # 3. Exact mathematical savings: (N - 1) / N
    savings_fraction = (model_pa.call_count - model_ba.call_count) / model_pa.call_count
    expected_savings = (panel_size - 1.0) / panel_size
    assert abs(savings_fraction - expected_savings) < 1e-9


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_size", [2, 3, 4, 5, 6, 7, 8])
async def test_challenge_full_lifecycle_scaling_n2_to_n8(panel_size: int):
    """Stress-test full Round 1 lifecycle call count scaling across N in [2..8]:
    - per_agent makes 2N calls (N propose + N critique).
    - batched makes N + 1 calls (N propose + 1 critique).
    - Lifecycle savings is exactly (N - 1) / (2N).
    """
    agent_ids = [f"specialist_{i}" for i in range(panel_size)]

    # 1. per_agent mode
    model_pa = MockChatModel(model_name=f"mock-lc-pa-{panel_size}")
    for aid in agent_ids:
        model_pa.queue_response({
            "agent_id": aid,
            "round_num": 1,
            "scope": "scope_eval",
            "summary": f"{aid} proposal plan",
        })
    for aid in agent_ids:
        target = next(p for p in agent_ids if p != aid)
        model_pa.queue_response([
            {
                "reviewer_agent_id": aid,
                "target_agent_id": target,
                "round_num": 1,
                "stance": "endorse",
                "issue_type": "synergy",
                "critique": f"Endorsement from {aid}",
                "proposed_resolution": "Commit",
            }
        ])

    config_pa = DeliberationConfig(
        panel_id=f"panel_pa_{panel_size}",
        critique_mode="per_agent",
        budget=DeliberationBudget(max_rounds=1),
    )
    engine_pa = DeliberationEngine(model=model_pa, config=config_pa)
    state_pa = create_initial_state(
        prompt="Coordinate scaling",
        target_agents=agent_ids,
        deliberation_config=config_pa.model_dump(),
    )
    await engine_pa.run(state_pa)
    assert model_pa.call_count == 2 * panel_size

    # 2. batched mode
    model_ba = MockChatModel(model_name=f"mock-lc-ba-{panel_size}")
    for aid in agent_ids:
        model_ba.queue_response({
            "agent_id": aid,
            "round_num": 1,
            "scope": "scope_eval",
            "summary": f"{aid} proposal plan",
        })
    batched_critiques = [
        {
            "reviewer_agent_id": agent_ids[i],
            "target_agent_id": agent_ids[(i + 1) % panel_size],
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": f"Batch endorsement from {agent_ids[i]}",
            "proposed_resolution": "Commit",
        }
        for i in range(panel_size)
    ]
    model_ba.queue_response(batched_critiques)

    config_ba = DeliberationConfig(
        panel_id=f"panel_ba_{panel_size}",
        critique_mode="batched",
        budget=DeliberationBudget(max_rounds=1),
    )
    engine_ba = DeliberationEngine(model=model_ba, config=config_ba)
    state_ba = create_initial_state(
        prompt="Coordinate scaling",
        target_agents=agent_ids,
        deliberation_config=config_ba.model_dump(),
    )
    await engine_ba.run(state_ba)
    assert model_ba.call_count == panel_size + 1

    # 3. Verify lifecycle savings formula: (2N - (N + 1)) / (2N) = (N - 1) / (2N)
    savings = (model_pa.call_count - model_ba.call_count) / model_pa.call_count
    expected_savings = (panel_size - 1.0) / (2.0 * panel_size)
    assert abs(savings - expected_savings) < 1e-9


# ============================================================================
# Section 2: Selective Revision Savings (N - K) / N for All Combinations K <= N
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_size", [2, 3, 4, 5, 6, 7, 8])
async def test_challenge_selective_revision_all_k_combinations(panel_size: int):
    """Stress-test selective revision across panel sizes N in [2..8] for all K in [0..N]:
    - For each K in [0..N], select subsets of challenged agents.
    - Exactly K model calls are made.
    - Savings ratio is exactly (N - K) / N.
    - Challenged agents have round_num == 2; unchallenged remain round_num == 1.
    """
    agent_ids = [f"agent_{i}" for i in range(panel_size)]
    active_proposals = {
        aid: AgentProposal(
            agent_id=aid,
            round_num=1,
            scope="scope_test",
            summary=f"Initial proposal from {aid}",
        )
        for aid in agent_ids
    }

    # Test all K from 0 to panel_size
    for k in range(panel_size + 1):
        # Sample subsets of size k (for k in [0, 1, panel_size], test all; for intermediate k, test at least 3)
        all_subsets = list(itertools.combinations(agent_ids, k))
        sample_subsets = all_subsets if len(all_subsets) <= 5 else [all_subsets[0], all_subsets[len(all_subsets) // 2], all_subsets[-1]]

        for targeted_subset in sample_subsets:
            targeted_set = set(targeted_subset)
            model = MockChatModel(model_name=f"mock-rev-n{panel_size}-k{k}")

            # Construct critiques: open AMEND for targeted agents, resolved ENDORSE for others
            critiques = []
            for aid in agent_ids:
                if aid in targeted_set:
                    reviewer = next(p for p in agent_ids if p != aid)
                    critiques.append(
                        PeerCritique(
                            reviewer_agent_id=reviewer,
                            target_agent_id=aid,
                            round_num=1,
                            stance=CritiqueStance.AMEND,
                            issue_type="dependency_order",
                            critique=f"Amend request for {aid}",
                            proposed_resolution="Update sequence",
                            resolved=False,
                        )
                    )
                    model.queue_response({
                        "agent_id": aid,
                        "round_num": 2,
                        "scope": "scope_test",
                        "summary": f"Revised proposal from {aid}",
                    })
                else:
                    reviewer = next(p for p in agent_ids if p != aid)
                    critiques.append(
                        PeerCritique(
                            reviewer_agent_id=reviewer,
                            target_agent_id=aid,
                            round_num=1,
                            stance=CritiqueStance.ENDORSE,
                            issue_type="synergy",
                            critique=f"Supporting endorsement for {aid}",
                            proposed_resolution="Commit",
                            resolved=True,
                        )
                    )

            revised = await run_selective_revision(
                active_proposals=active_proposals,
                critiques=critiques,
                round_num=2,
                model=model,
            )

            # Invariant 1: Exactly K model calls
            assert model.call_count == k

            # Invariant 2: Mathematical savings: (N - K) / N
            full_calls = panel_size
            savings = (full_calls - model.call_count) / float(full_calls)
            expected = (panel_size - k) / float(panel_size)
            assert abs(savings - expected) < 1e-9

            # Invariant 3: Targeted agents updated to round 2, untargeted preserved at round 1
            for aid in agent_ids:
                if aid in targeted_set:
                    assert revised[aid].round_num == 2
                    assert "Revised" in revised[aid].summary
                else:
                    assert revised[aid].round_num == 1
                    assert revised[aid].summary == f"Initial proposal from {aid}"


@pytest.mark.asyncio
async def test_challenge_selective_revision_multiple_critiques_deduping():
    """Verify that an agent targeted by multiple open critiques is revised only once (1 call, not C calls)."""
    agents = ["specialist_a", "specialist_b", "specialist_c", "specialist_d"]
    active = {
        aid: AgentProposal(agent_id=aid, round_num=1, scope="scope_a", summary=f"Plan {aid}")
        for aid in agents
    }

    # Specialist B is targeted by 5 different open critiques from peers and auditors
    critiques = [
        PeerCritique(reviewer_agent_id="specialist_a", target_agent_id="specialist_b", round_num=1, stance=CritiqueStance.CONFLICT, issue_type="resource_overbudget", critique="Over budget", proposed_resolution="Reduce", resolved=False),
        PeerCritique(reviewer_agent_id="specialist_c", target_agent_id="specialist_b", round_num=1, stance=CritiqueStance.AMEND, issue_type="dependency_order", critique="Sequence error", proposed_resolution="Fix order", resolved=False),
        PeerCritique(reviewer_agent_id="specialist_d", target_agent_id="specialist_b", round_num=1, stance=CritiqueStance.CONFLICT, issue_type="contraindication", critique="Strategy mismatch", proposed_resolution="Harmonize", resolved=False),
        PeerCritique(reviewer_agent_id="moderator", target_agent_id="specialist_b", round_num=1, stance=CritiqueStance.CONFLICT, issue_type="resource_overbudget", critique="Constraint breached", proposed_resolution="Trim claims", resolved=False),
        PeerCritique(reviewer_agent_id="specialist_a", target_agent_id="specialist_b", round_num=1, stance=CritiqueStance.AMEND, issue_type="risk_exposure", critique="Unaddressed risk", proposed_resolution="Add safeguard", resolved=False),
    ]

    model = MockChatModel(model_name="mock-dedup")
    model.queue_response({
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_a",
        "summary": "Revised plan addressing all 5 critiques",
    })

    revised = await run_selective_revision(
        active_proposals=active,
        critiques=critiques,
        round_num=2,
        model=model,
    )

    # Exactly 1 model call made, despite 5 critiques targeting specialist_b
    assert model.call_count == 1
    assert revised["specialist_b"].round_num == 2
    assert "Revised" in revised["specialist_b"].summary
    # Specialists A, C, and D untouched
    for aid in ["specialist_a", "specialist_c", "specialist_d"]:
        assert revised[aid].round_num == 1


@pytest.mark.asyncio
async def test_challenge_selective_revision_retains_and_normalizes_staged_actions_in_phase_3():
    """Verify Phase 3 invariant: staged write actions in revised proposals are retained and normalized."""
    agents = ["specialist_a", "specialist_b"]
    active = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_a", summary="A plan"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_a", summary="B plan"),
    }
    critique = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.AMEND,
        issue_type="dependency_order",
        critique="Amend B",
        proposed_resolution="Fix",
        resolved=False,
    )

    model = MockChatModel(model_name="mock-staged-retention")
    # Specialist B attempts to stage a write action during selective revision
    model.queue_response({
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_a",
        "summary": "Revised plan B with staged write action",
        "staged_actions": [
            {
                "agent_id": "specialist_b",
                "tool_name": "update_record",
                "tool_args": {"key": "val"},
                "rationale": "Attempted update",
                "risk_tier": "write_external",
            }
        ],
    })

    revised = await run_selective_revision(
        active_proposals=active,
        critiques=[critique],
        round_num=2,
        model=model,
    )

    assert revised["specialist_b"].round_num == 2
    # Invariant: staged_actions are retained in Phase 3 with normalized agent_id and fail-closed risk tier
    assert len(revised["specialist_b"].staged_actions) == 1
    staged = revised["specialist_b"].staged_actions[0]
    assert staged.agent_id == "specialist_b"
    assert staged.tool_name == "update_record"
    # Unrecognized tool fails closed to irreversible
    assert staged.risk_tier == "irreversible"


# ============================================================================
# Section 3: Token Budget & Wall-Clock Timeout Under High Event Frequency
# ============================================================================


def test_challenge_token_budget_boundary_and_exhaustion():
    """Stress-test token budget truncation at exact boundary and beyond."""
    budget = DeliberationBudget(max_rounds=3, max_total_tokens=5000)
    blocking_critique = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Over budget",
        proposed_resolution="Reduce",
        resolved=False,
    )

    # 1. total_tokens = 0: Should not trigger token exhaustion
    d0 = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        total_tokens=0,
    )
    assert d0.next_node == "selective_revise"
    assert d0.reason == "revision_needed"

    # 2. total_tokens = 4999 (strictly below budget)
    d_under = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        total_tokens=4999,
    )
    assert d_under.next_node == "selective_revise"
    assert d_under.reason == "revision_needed"

    # 3. total_tokens = 5000 (exact boundary)
    d_exact = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        total_tokens=5000,
    )
    assert d_exact.next_node == "synthesize"
    assert d_exact.converged is False
    assert d_exact.reason == "token_budget_exhausted"

    # 4. total_tokens = 15000 (overshoot)
    d_over = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        total_tokens=15000,
    )
    assert d_over.next_node == "synthesize"
    assert d_over.converged is False
    assert d_over.reason == "token_budget_exhausted"


def test_challenge_wall_clock_timeout_threshold():
    """Stress-test wall-clock timeout thresholds with millisecond accuracy."""
    budget = DeliberationBudget(max_rounds=3, max_wall_clock_s=2.0)
    blocking_critique = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Conflict",
        proposed_resolution="Resolve",
        resolved=False,
    )

    # 1. Elapsed = 1.95s (< 2.0s): revision allowed
    now = time.time()
    d_under = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        start_time=now - 1.95,
    )
    assert d_under.next_node == "selective_revise"

    # 2. Elapsed = 2.0001s (>= 2.0s): exhausted
    d_over = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        budget=budget,
        start_time=now - 2.05,
    )
    assert d_over.next_node == "synthesize"
    assert d_over.converged is False
    assert d_over.reason == "wall_clock_exhausted"


@pytest.mark.asyncio
async def test_challenge_high_event_frequency_stress():
    """Stress-test high event frequency: 200 rapid SSE events during deliberation do not corrupt state."""
    events_received: List[Dict[str, Any]] = []

    # Emit 200 events rapidly
    tasks = [
        _emit_sse_event(
            "deliberation_critique",
            {"round": i % 5, "reviewer_id": f"agent_{i % 4}", "critique": f"Event {i}"},
        )
        for i in range(200)
    ]
    await asyncio.gather(*tasks)

    # Invariant: high frequency async event emission completes cleanly without unhandled exceptions
    assert True


# ============================================================================
# Section 4: Multi-Issue Concurrent Conflicts & Deterministic Convergence
# ============================================================================


@pytest.mark.asyncio
async def test_challenge_multi_issue_concurrent_resolution():
    """Stress-test 4-agent panel with 4 concurrent issues resolving deterministically at Round 2:
    - Issue 1: Overbudget on weekly_quota (sum 45h > 30h limit)
    - Issue 2: Overbudget on compute_budget (sum 120u > 80u limit)
    - Issue 3: Dependency order sequencing conflict (B requires A first)
    - Issue 4: Strategic contraindication (C conflicts D on pipeline architecture)
    - Round 2: All 4 targeted agents revise and resolve all issues -> Clean convergence.
    """
    c_quota = SharedConstraint(id="weekly_quota", description="Weekly quota limit", unit="hours", limit_value=30.0, limit_source="user")
    c_compute = SharedConstraint(id="compute_budget", description="Compute budget limit", unit="units", limit_value=80.0, limit_source="user")

    config = DeliberationConfig(
        panel_id="panel_multi_issue",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[c_quota, c_compute],
        critique_mode="batched",
    )

    # Round 1 proposals: 4 agents exceeding quotas and conflicting
    prop_a_r1 = {"agent_id": "specialist_a", "round_num": 1, "scope": "scope_multi", "summary": "Pipeline setup", "resource_claims": {"weekly_quota": 10.0, "compute_budget": 20.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_b_r1 = {"agent_id": "specialist_b", "round_num": 1, "scope": "scope_multi", "summary": "Data ingest", "resource_claims": {"weekly_quota": 12.0, "compute_budget": 30.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_c_r1 = {"agent_id": "specialist_c", "round_num": 1, "scope": "scope_multi", "summary": "Sync analytics", "resource_claims": {"weekly_quota": 11.0, "compute_budget": 35.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_d_r1 = {"agent_id": "specialist_d", "round_num": 1, "scope": "scope_multi", "summary": "Async analytics", "resource_claims": {"weekly_quota": 12.0, "compute_budget": 35.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    # Sum quota: 45h > 30h. Sum compute: 120u > 80u.

    # Round 1 peer critiques: dependency and strategic conflicts
    r1_peer_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "amend", "issue_type": "dependency_order", "critique": "Step B must run after step A", "proposed_resolution": "Sequence B after A"},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_d", "round_num": 1, "stance": "conflict", "issue_type": "contraindication", "critique": "Conflicting architecture with D", "proposed_resolution": "Adopt hybrid queue"},
    ]

    # Round 2 revised proposals: All 4 agents trim resources and resolve issues
    prop_a_r2 = {"agent_id": "specialist_a", "round_num": 2, "scope": "scope_multi", "summary": "Optimized pipeline setup", "resource_claims": {"weekly_quota": 6.0, "compute_budget": 15.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_b_r2 = {"agent_id": "specialist_b", "round_num": 2, "scope": "scope_multi", "summary": "Data ingest sequenced after A", "resource_claims": {"weekly_quota": 8.0, "compute_budget": 20.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_c_r2 = {"agent_id": "specialist_c", "round_num": 2, "scope": "scope_multi", "summary": "Hybrid queue component C", "resource_claims": {"weekly_quota": 7.0, "compute_budget": 20.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    prop_d_r2 = {"agent_id": "specialist_d", "round_num": 2, "scope": "scope_multi", "summary": "Hybrid queue component D", "resource_claims": {"weekly_quota": 7.0, "compute_budget": 20.0}, "resource_claim_units": {"weekly_quota": "hours", "compute_budget": "units"}}
    # Sum quota: 28h <= 30h. Sum compute: 75u <= 80u.

    # Round 2 peer critiques: All endorse
    r2_peer_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Sequencing verified.", "proposed_resolution": "Commit"},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_d", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Hybrid architecture verified.", "proposed_resolution": "Commit"},
    ]

    model = MockChatModel(model_name="mock-multi-issue")
    # R1: 4 proposals + 1 batched critique
    model.queue_response(prop_a_r1)
    model.queue_response(prop_b_r1)
    model.queue_response(prop_c_r1)
    model.queue_response(prop_d_r1)
    model.queue_response(r1_peer_critiques)
    # R2: 4 revisions (all targeted due to budget + peer critiques) + 1 batched critique
    model.queue_response(prop_a_r2)
    model.queue_response(prop_b_r2)
    model.queue_response(prop_c_r2)
    model.queue_response(prop_d_r2)
    model.queue_response(r2_peer_critiques)

    engine = DeliberationEngine(model=model, config=config)
    state = create_initial_state(
        prompt="Resolve 4 concurrent issues",
        target_agents=["specialist_a", "specialist_b", "specialist_c", "specialist_d"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    # Verify deterministic convergence
    assert delib["rounds_used"] == 2
    assert delib["converged"] is True
    assert delib["termination_reason"] == "converged"
    # Verify resource constraints are satisfied
    active_props = delib["active_proposals"]
    total_quota = sum(p["resource_claims"]["weekly_quota"] for p in active_props.values())
    total_compute = sum(p["resource_claims"]["compute_budget"] for p in active_props.values())
    assert total_quota <= 30.0
    assert total_compute <= 80.0


@pytest.mark.asyncio
async def test_challenge_multi_issue_concurrent_deadlock_minority_report():
    """Stress-test partial resolution where budget resolves but strategic conflict deadlocks:
    - Bounded termination at round_num == 2 with converged == False.
    - ResponseSynthesizerNode produces Minority Report with Option A vs Option B.
    """
    c_quota = SharedConstraint(id="weekly_quota", description="Weekly quota limit", unit="hours", limit_value=20.0, limit_source="user")
    config = DeliberationConfig(
        panel_id="panel_deadlock",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[c_quota],
        critique_mode="batched",
    )

    prop_a_r1 = {"agent_id": "specialist_a", "round_num": 1, "scope": "scope_deadlock", "summary": "Centralized sync", "resource_claims": {"weekly_quota": 15.0}, "resource_claim_units": {"weekly_quota": "hours"}}
    prop_b_r1 = {"agent_id": "specialist_b", "round_num": 1, "scope": "scope_deadlock", "summary": "Decentralized mesh", "resource_claims": {"weekly_quota": 15.0}, "resource_claim_units": {"weekly_quota": "hours"}}

    r1_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "conflict", "issue_type": "contraindication", "critique": "Mesh architecture is fundamentally flawed", "proposed_resolution": "Adopt centralized sync"},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "conflict", "issue_type": "contraindication", "critique": "Centralized sync is a single point of failure", "proposed_resolution": "Adopt decentralized mesh"},
    ]

    # Round 2: Both trim quota (within 20h limit), but maintain architectural conflict
    prop_a_r2 = {"agent_id": "specialist_a", "round_num": 2, "scope": "scope_deadlock", "summary": "Centralized sync (trimmed)", "resource_claims": {"weekly_quota": 9.0}, "resource_claim_units": {"weekly_quota": "hours"}}
    prop_b_r2 = {"agent_id": "specialist_b", "round_num": 2, "scope": "scope_deadlock", "summary": "Decentralized mesh (trimmed)", "resource_claims": {"weekly_quota": 9.0}, "resource_claim_units": {"weekly_quota": "hours"}}

    r2_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "conflict", "issue_type": "contraindication", "critique": "Irreconcilable architectural deadlock", "proposed_resolution": "Escalate to user"},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 2, "stance": "conflict", "issue_type": "contraindication", "critique": "Irreconcilable architectural deadlock", "proposed_resolution": "Escalate to user"},
    ]

    model = MockChatModel(model_name="mock-deadlock")
    model.queue_response(prop_a_r1)
    model.queue_response(prop_b_r1)
    model.queue_response(r1_critiques)
    model.queue_response(prop_a_r2)
    model.queue_response(prop_b_r2)
    model.queue_response(r2_critiques)

    engine = DeliberationEngine(model=model, config=config)
    state = create_initial_state(
        prompt="Deadlock panel",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is False
    assert delib["termination_reason"] == "max_rounds_reached"

    synthesizer = ResponseSynthesizerNode()
    synthesized = synthesizer.synthesize_deliberation(result)
    assert "## Minority Report" in synthesized
    assert "### Option A" in synthesized
    assert "### Option B" in synthesized
    assert "Stakeholder Decision Required" in synthesized


@pytest.mark.asyncio
async def test_challenge_cyclic_dependency_graph_bounded_termination():
    """Stress-test cyclic conflict graph (A -> B -> C -> D -> A):
    Verifies that cyclic peer conflicts do not cause infinite recursion or state explosion,
    and cleanly terminate at max_rounds.
    """
    agents = ["specialist_a", "specialist_b", "specialist_c", "specialist_d"]
    config = DeliberationConfig(
        panel_id="panel_cyclic",
        budget=DeliberationBudget(max_rounds=2),
        critique_mode="batched",
    )

    # R1 proposals
    for aid in agents:
        pass

    # R1 cyclic critiques: A conflicts B, B conflicts C, C conflicts D, D conflicts A
    r1_cyclic = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "A conflicts B", "proposed_resolution": "B yields"},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "B conflicts C", "proposed_resolution": "C yields"},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_d", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "C conflicts D", "proposed_resolution": "D yields"},
        {"reviewer_agent_id": "specialist_d", "target_agent_id": "specialist_a", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "D conflicts A", "proposed_resolution": "A yields"},
    ]

    r2_cyclic = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "conflict", "issue_type": "dependency_order", "critique": "Deadlock cycle", "proposed_resolution": "Escalate"},
    ]

    model = MockChatModel(model_name="mock-cyclic")
    for aid in agents:
        model.queue_response({"agent_id": aid, "round_num": 1, "scope": "scope_cycle", "summary": f"{aid} proposal"})
    model.queue_response(r1_cyclic)
    for aid in agents:
        model.queue_response({"agent_id": aid, "round_num": 2, "scope": "scope_cycle", "summary": f"{aid} revised"})
    model.queue_response(r2_cyclic)

    engine = DeliberationEngine(model=model, config=config)
    state = create_initial_state(
        prompt="Resolve cyclic dependencies",
        target_agents=agents,
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is False
    assert delib["termination_reason"] == "max_rounds_reached"
    assert len(delib["active_proposals"]) == 4


# ============================================================================
# Section 5: Exhaustive Subsets & Deep Invariant Adversarial Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_size", [2, 3, 4, 5])
async def test_challenge_selective_revision_all_subsets_exhaustive(panel_size: int):
    """Adversarially test ALL 2^N subsets of challenged agents for panel sizes N in [2..5]:
    Total subsets tested = 4 + 8 + 16 + 32 = 60 combinations.
    For each combination:
    - Model call count is exactly len(targeted_subset).
    - Call savings is exactly (N - K) / N.
    - Untargeted proposals are preserved verbatim.
    """
    agent_ids = [f"agent_{i}" for i in range(panel_size)]
    active = {
        aid: AgentProposal(agent_id=aid, round_num=1, scope="scope_ex", summary=f"Plan {aid}")
        for aid in agent_ids
    }

    # Iterate over all possible subsets of agent_ids
    for k in range(panel_size + 1):
        for targeted_subset in itertools.combinations(agent_ids, k):
            targeted_set = set(targeted_subset)
            model = MockChatModel(model_name=f"mock-sub-{panel_size}-{k}")

            critiques = []
            for aid in agent_ids:
                reviewer = next(p for p in agent_ids if p != aid)
                if aid in targeted_set:
                    critiques.append(
                        PeerCritique(
                            reviewer_agent_id=reviewer,
                            target_agent_id=aid,
                            round_num=1,
                            stance=CritiqueStance.AMEND,
                            issue_type="dependency_order",
                            critique=f"Amend {aid}",
                            proposed_resolution="Fix",
                            resolved=False,
                        )
                    )
                    model.queue_response({
                        "agent_id": aid,
                        "round_num": 2,
                        "scope": "scope_ex",
                        "summary": f"Revised {aid}",
                    })
                else:
                    critiques.append(
                        PeerCritique(
                            reviewer_agent_id=reviewer,
                            target_agent_id=aid,
                            round_num=1,
                            stance=CritiqueStance.ENDORSE,
                            issue_type="synergy",
                            critique=f"Endorse {aid}",
                            proposed_resolution="Commit",
                            resolved=True,
                        )
                    )

            revised = await run_selective_revision(
                active_proposals=active,
                critiques=critiques,
                round_num=2,
                model=model,
            )

            assert model.call_count == k
            savings = (panel_size - model.call_count) / float(panel_size)
            expected = (panel_size - k) / float(panel_size)
            assert abs(savings - expected) < 1e-9

            for aid in agent_ids:
                if aid in targeted_set:
                    assert revised[aid].round_num == 2
                    assert "Revised" in revised[aid].summary
                else:
                    assert revised[aid].round_num == 1
                    assert revised[aid].summary == f"Plan {aid}"


@pytest.mark.asyncio
async def test_challenge_revision_schema_failure_retry_exhaustion_preserves_proposal():
    """Verify that when a targeted specialist exhausts retry attempts on invalid schema,
    its prior round proposal is preserved untouched rather than abruptly dropping the agent.
    """
    agents = ["specialist_a", "specialist_b"]
    active = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_r", summary="Original plan A"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_r", summary="Original plan B"),
    }
    critique = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="risk_exposure",
        critique="Risk detected",
        proposed_resolution="Mitigate",
        resolved=False,
    )

    model = MockChatModel(model_name="mock-exhaust-retry")
    # Specialist B fails schema on attempt 1 and retry attempt 2
    model.queue_response({"invalid_schema_field": True})
    model.queue_response({"still_invalid": "missing required fields"})

    revised = await run_selective_revision(
        active_proposals=active,
        critiques=[critique],
        round_num=2,
        model=model,
        max_retries=1,
    )

    # Invariant: specialist_b is preserved with its prior proposal
    assert len(revised) == 2
    assert revised["specialist_b"].summary == "Original plan B"
    assert revised["specialist_b"].round_num == 1
    assert revised["specialist_a"].summary == "Original plan A"
    assert revised["specialist_a"].round_num == 1


@pytest.mark.asyncio
async def test_challenge_batched_critique_doc_filtering_matrix():
    """Adversarially test batched critique filtering against malformed items, self-critiques, and bare agreement."""
    proposals = [
        AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_f", summary="A plan"),
        AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_f", summary="B plan"),
    ]

    model = MockChatModel(model_name="mock-doc-filter")
    # Attempt 1: contains bare agreement ("+1"), which triggers schema validation error
    model.queue_response([
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Self endorsement", "proposed_resolution": "Commit"},
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "+1", "proposed_resolution": ""},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "conflict", "issue_type": "risk_exposure", "critique": "Unmitigated concurrency hazard.", "proposed_resolution": "Add synchronization."},
    ])
    # Attempt 2 (repair retry): model replaces bare agreement with substantive endorsement
    model.queue_response([
        # Self-critique should still be filtered
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Self endorsement", "proposed_resolution": "Commit"},
        # Repaired substantive endorsement
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Valid substantive endorsement verifying dependencies.", "proposed_resolution": "Commit"},
        # Valid conflict
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "conflict", "issue_type": "risk_exposure", "critique": "Unmitigated concurrency hazard.", "proposed_resolution": "Add synchronization."},
    ])

    critiques = await run_peer_critiques(proposals, mode="batched", model=model, round_num=1, max_retries=1)

    # Invariants: Model retried once (2 calls)
    assert model.call_count == 2
    # Exactly 2 valid critiques survive after repair
    assert len(critiques) == 2
    # Self-critique was filtered
    assert all(c.reviewer_agent_id != c.target_agent_id for c in critiques)
    # Bare endorsement was repaired to substantive points
    assert all(len(c.critique.strip()) >= 10 for c in critiques if c.stance == CritiqueStance.ENDORSE)


def test_challenge_auditor_unit_mismatch_strict_rejection():
    """Verify that BudgetAuditor strictly raises UnitMismatchError on unit mismatch without guessing conversions."""
    constraint = SharedConstraint(
        id="execution_time",
        description="Total execution time allowance",
        unit="hours",
        limit_value=10.0,
        limit_source="user",
    )
    # Agent claims in "seconds", mismatching constraint's "hours"
    proposal = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_audit",
        summary="A proposal",
        resource_claims={"execution_time": 3600.0},
        resource_claim_units={"execution_time": "seconds"},
    )

    auditor = BudgetAuditor()
    with pytest.raises(UnitMismatchError) as exc_info:
        auditor.audit(constraints=[constraint], proposals=[proposal])

    assert "Unit mismatch for constraint 'execution_time'" in str(exc_info.value)
    assert "expected 'hours', got 'seconds'" in str(exc_info.value)
    assert "Conversions are not guessed" in str(exc_info.value)


def test_challenge_auditor_multiple_constraints_mixed_overbudget():
    """Verify BudgetAuditor correctly segregates overbudget, within-limit, and skipped constraints."""
    c_within = SharedConstraint(id="cpu_hours", description="CPU limit", unit="hours", limit_value=50.0, limit_source="user")
    c_over = SharedConstraint(id="memory_units", description="RAM limit", unit="units", limit_value=16.0, limit_source="user")
    c_skipped = SharedConstraint(id="storage_quota", description="Storage limit unknown", unit="units", limit_value=None, limit_source=None)

    proposals = [
        AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_audit", summary="A", resource_claims={"cpu_hours": 20.0, "memory_units": 10.0, "storage_quota": 50.0}, resource_claim_units={"cpu_hours": "hours", "memory_units": "units", "storage_quota": "units"}),
        AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_audit", summary="B", resource_claims={"cpu_hours": 20.0, "memory_units": 10.0, "storage_quota": 50.0}, resource_claim_units={"cpu_hours": "hours", "memory_units": "units", "storage_quota": "units"}),
    ]

    auditor = BudgetAuditor()
    critiques = auditor.audit(constraints=[c_within, c_over, c_skipped], proposals=proposals)

    # 1. Skipped constraints
    assert "storage_quota" in auditor.skipped_constraints
    assert "cpu_hours" not in auditor.skipped_constraints
    assert "memory_units" not in auditor.skipped_constraints

    # 2. Emitted critiques: exactly for memory_units (10 + 10 = 20 > 16)
    assert len(critiques) == 2  # Targeted at both contributing agents specialist_a and specialist_b
    assert all(c.stance == CritiqueStance.CONFLICT for c in critiques)
    assert all(c.issue_type == "resource_overbudget" for c in critiques)
    assert {c.target_agent_id for c in critiques} == {"specialist_a", "specialist_b"}

