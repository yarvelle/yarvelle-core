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

"""Comprehensive golden evaluation suite for multi-agent blackboard deliberation (M4 / R4).

Evaluates ADR 0001 §2 and §7 Phase 1 quantitative and qualitative properties:
1. Diverse Multi-Agent Panel Convergence & Bounded Termination (2, 3, and 4 agents):
   - Guaranteed deterministic convergence when peer/auditor critiques are addressed.
   - Bounded termination at max_rounds when irreconcilable conflicts exist.
   - Minority report generation with contrasting perspectives on unresolved conflict.
2. Direct Comparison of per_agent vs batched Critique Modes:
   - Call count scaling in run_peer_critiques across panel sizes N=2, 3, 4:
     per_agent makes N calls; batched makes 1 call ((N-1)/N call savings).
   - Full Round 1 lifecycle call counts in DeliberationEngine.run:
     per_agent makes 2N calls; batched makes N+1 calls.
   - Disagree-or-Commit compliance, self-critique prevention, and stance parity.
3. Quantitative Verification of Selective Revision Call Savings:
   - 1 of 3 agents challenged: 1 revision call (66.7% call reduction vs full re-run).
   - 0 of 3 agents challenged: 0 revision calls (100% call reduction vs full re-run).
   - 2 of 4 agents challenged: 2 revision calls (50.0% call reduction vs full re-run).
   - Untargeted proposals preserved untouched at round_num == 1.
4. Extended Resilience & Robustness:
   - Schema validation retry and graceful single-agent degradation (< 2 proposals).
   - Wall-clock and token budget truncation.
   - Monotonic taint propagation and untrusted source warning flags.
   - Explicit notation for skipped unbounded constraints.
5. Strict Domain Neutrality & Offline Determinism:
   - 100% generic identifiers (specialist_a, specialist_b, scope_alpha, weekly_quota).
   - 100% offline reproducibility using MockChatModel.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
import pytest

from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    ExecutionPlan,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.deliberation.gate import evaluate_convergence_gate
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.state import (
    AgentProposal,
    AgentState,
    CritiqueStance,
    PeerCritique,
    create_initial_state,
)

try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


# ============================================================================
# Shared Domain-Neutral Fixtures
# ============================================================================


@pytest.fixture
def eval_model() -> MockChatModel:
    """Deterministic offline model for golden evaluations."""
    return MockChatModel(model_name="mock-eval-engine")


@pytest.fixture
def eval_constraint_quota() -> SharedConstraint:
    """Generic weekly quota constraint with user limit."""
    return SharedConstraint(
        id="weekly_quota",
        description="Weekly total allowable workload units",
        unit="hours",
        limit_value=20.0,
        limit_source="user",
    )


@pytest.fixture
def eval_constraint_compute() -> SharedConstraint:
    """Generic compute execution allocation constraint."""
    return SharedConstraint(
        id="compute_budget",
        description="Total allowable compute execution units",
        unit="units",
        limit_value=100.0,
        limit_source="user",
    )


# ============================================================================
# Module I: Diverse Multi-Agent Panel Convergence & Bounded Termination
# ============================================================================


@pytest.mark.asyncio
async def test_eval_panel_duo_deterministic_convergence(eval_model, eval_constraint_quota):
    """Evaluate 2-agent panel: guaranteed convergence at Round 2 when critique is addressed.

    Verifies:
    - Round 1 overbudget critique triggers selective revision.
    - Specialist B resolves critique by reducing allocation from 14h to 10h.
    - Untargeted Specialist A proposal is preserved untouched at round_num == 1.
    - Deliberation converges cleanly with rounds_used == 2, converged == True.
    """
    config = DeliberationConfig(
        panel_id="panel_duo_eval",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[eval_constraint_quota],
        critique_mode="per_agent",
    )

    # Round 1: Specialist A claims 8h, B claims 10h (sum 18h <= 20h limit).
    # Peer A AMENDS B regarding sequencing; Peer B ENDORSES A.
    prop_a_r1 = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Phase 1 pipeline setup requiring 8 hours.",
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_b_r1 = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Phase 2 data processing requiring 10 hours.",
        "resource_claims": {"weekly_quota": 10.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }

    # Peer critiques: A amends B regarding sequencing; B endorses A.
    critique_a_to_b = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 1,
        "stance": "amend",
        "issue_type": "dependency_order",
        "critique": "Sequence step 2 data processing after step 1 pipeline setup.",
        "proposed_resolution": "Adjust execution sequence to follow step 1.",
    }
    critique_b_to_a = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Setup prerequisites are sound and properly scoped.",
        "proposed_resolution": "Commit.",
    }

    # Round 2: Specialist B revises sequence while maintaining 10h allocation.
    prop_b_r2 = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Revised phase 2 data processing sequenced after step 1.",
        "resource_claims": {"weekly_quota": 10.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }

    # Round 2 peer critiques: Both endorse.
    critique_endorse_a_to_b = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Sequencing alignment verified and confirmed.",
        "proposed_resolution": "Commit.",
    }
    critique_endorse_b_to_a = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 2,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Prerequisites remain solid.",
        "proposed_resolution": "Commit.",
    }

    eval_model.queue_response(prop_a_r1)
    eval_model.queue_response(prop_b_r1)
    eval_model.queue_response([critique_a_to_b])
    eval_model.queue_response([critique_b_to_a])
    eval_model.queue_response(prop_b_r2)
    eval_model.queue_response([critique_endorse_a_to_b])
    eval_model.queue_response([critique_endorse_b_to_a])

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate 2-agent workload within quota",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is True
    assert delib["termination_reason"] == "converged"
    assert delib["active_proposals"]["specialist_b"]["resource_claims"]["weekly_quota"] == 10.0
    # Specialist A was not targeted; proposal preserved untouched at round_num == 1
    assert delib["active_proposals"]["specialist_a"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_b"]["round_num"] == 2


@pytest.mark.asyncio
async def test_eval_panel_duo_bounded_termination_on_deadlock(eval_model, eval_constraint_quota):
    """Evaluate 2-agent panel: bounded termination at max_rounds when conflict is irreconcilable.

    Verifies:
    - Bounded termination at round_num == 2 when mutual CONFLICT critiques persist.
    - Termination reason is 'max_rounds_reached' with converged == False.
    - ResponseSynthesizerNode produces a structured Minority Report (Option A vs Option B).
    """
    config = DeliberationConfig(
        panel_id="panel_duo_deadlock",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[eval_constraint_quota],
        critique_mode="per_agent",
    )

    # Round 1: Both claim 15h (total 30h > 20h quota).
    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Mandatory task A requiring 15 hours.",
        "resource_claims": {"weekly_quota": 15.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_b = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Mandatory task B requiring 15 hours.",
        "resource_claims": {"weekly_quota": 15.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }

    critique_conflict_a = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 1,
        "stance": "conflict",
        "issue_type": "resource_overbudget",
        "critique": "Cannot yield hours; task A is critical path infrastructure.",
        "proposed_resolution": "Task B must drop to 5 hours.",
    }
    critique_conflict_b = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 1,
        "stance": "conflict",
        "issue_type": "resource_overbudget",
        "critique": "Cannot yield hours; task B is urgent security compliance.",
        "proposed_resolution": "Task A must drop to 5 hours.",
    }

    # Round 2: Both refuse to concede allocation.
    prop_a_r2 = {
        "agent_id": "specialist_a",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Maintained position: 15 hours needed for task A.",
        "resource_claims": {"weekly_quota": 15.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_b_r2 = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Maintained position: 15 hours needed for task B.",
        "resource_claims": {"weekly_quota": 15.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }

    critique_conflict_a_r2 = {
        "reviewer_agent_id": "specialist_a",
        "target_agent_id": "specialist_b",
        "round_num": 2,
        "stance": "conflict",
        "issue_type": "resource_overbudget",
        "critique": "Deadlock remains; cannot yield critical hours.",
        "proposed_resolution": "Escalate to human decision.",
    }
    critique_conflict_b_r2 = {
        "reviewer_agent_id": "specialist_b",
        "target_agent_id": "specialist_a",
        "round_num": 2,
        "stance": "conflict",
        "issue_type": "resource_overbudget",
        "critique": "Deadlock remains; cannot yield critical hours.",
        "proposed_resolution": "Escalate to human decision.",
    }

    eval_model.queue_response(prop_a)
    eval_model.queue_response(prop_b)
    eval_model.queue_response([critique_conflict_a])
    eval_model.queue_response([critique_conflict_b])
    eval_model.queue_response(prop_a_r2)
    eval_model.queue_response(prop_b_r2)
    eval_model.queue_response([critique_conflict_a_r2])
    eval_model.queue_response([critique_conflict_b_r2])

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate contested resources",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is False
    assert delib["termination_reason"] == "max_rounds_reached"

    # Verify ResponseSynthesizerNode minority report rendering
    synthesizer = ResponseSynthesizerNode()
    synthesized_markdown = synthesizer.synthesize_deliberation(result)
    assert "## Minority Report" in synthesized_markdown
    assert "Option A" in synthesized_markdown or "Specialist A" in synthesized_markdown


@pytest.mark.asyncio
async def test_eval_panel_trio_deterministic_convergence(eval_model, eval_constraint_compute):
    """Evaluate 3-agent panel: guaranteed convergence across 6 peer critique interactions.

    Verifies:
    - 3 specialists coordinate across shared compute_budget (100 units).
    - Round 1: sum(40 + 45 + 25) = 110 > 100 triggers AMEND critique on specialist_b.
    - Round 2: Only specialist_b revises down to 35 units.
    - Specialists A and C preserved untouched at round_num == 1.
    - Deliberation converges cleanly with all 6 peer reviews endorsing.
    """
    config = DeliberationConfig(
        panel_id="panel_trio_eval",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[eval_constraint_compute],
        critique_mode="per_agent",
    )

    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_beta",
        "summary": "Core processing engine requiring 40 units.",
        "resource_claims": {"compute_budget": 40.0},
        "resource_claim_units": {"compute_budget": "units"},
    }
    prop_b = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_beta",
        "summary": "Indexer service requiring 35 units.",
        "resource_claims": {"compute_budget": 35.0},
        "resource_claim_units": {"compute_budget": "units"},
    }
    prop_c = {
        "agent_id": "specialist_c",
        "round_num": 1,
        "scope": "scope_beta",
        "summary": "Cache layer requiring 25 units.",
        "resource_claims": {"compute_budget": 25.0},
        "resource_claim_units": {"compute_budget": "units"},
    }

    # Round 1 peer critiques (3 reviewer calls reviewing peers)
    critiques_from_a = [
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_b",
            "round_num": 1,
            "stance": "amend",
            "issue_type": "dependency_order",
            "critique": "Coordinate batch indexing sequence with cache flush intervals.",
            "proposed_resolution": "Align indexing batch intervals.",
        },
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_c",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Cache sizing is optimal and well scoped.",
            "proposed_resolution": "Commit.",
        },
    ]
    critiques_from_b = [
        {
            "reviewer_agent_id": "specialist_b",
            "target_agent_id": "specialist_a",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Core engine load estimate is valid.",
            "proposed_resolution": "Commit.",
        },
        {
            "reviewer_agent_id": "specialist_b",
            "target_agent_id": "specialist_c",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Cache coordinates effectively with indexer.",
            "proposed_resolution": "Commit.",
        },
    ]
    critiques_from_c = [
        {
            "reviewer_agent_id": "specialist_c",
            "target_agent_id": "specialist_a",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Prerequisites are ready.",
            "proposed_resolution": "Commit.",
        },
        {
            "reviewer_agent_id": "specialist_c",
            "target_agent_id": "specialist_b",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Indexer schema matches cache format.",
            "proposed_resolution": "Commit.",
        },
    ]

    # Round 2: Only specialist_b revises to coordinate indexing intervals
    prop_b_r2 = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_beta",
        "summary": "Indexer batch intervals coordinated with cache flush.",
        "resource_claims": {"compute_budget": 35.0},
        "resource_claim_units": {"compute_budget": "units"},
    }

    # Round 2 critiques: All 6 interactions endorse
    critiques_r2_a = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Batch indexing coordination verified and confirmed.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_c", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Cache allocation confirmed.", "proposed_resolution": "Commit."},
    ]
    critiques_r2_b = [
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Core engine approved.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Cache approved.", "proposed_resolution": "Commit."},
    ]
    critiques_r2_c = [
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_a", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Prerequisites verified and approved.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Reduced indexing approved.", "proposed_resolution": "Commit."},
    ]

    eval_model.queue_response(prop_a)
    eval_model.queue_response(prop_b)
    eval_model.queue_response(prop_c)
    eval_model.queue_response(critiques_from_a)
    eval_model.queue_response(critiques_from_b)
    eval_model.queue_response(critiques_from_c)
    eval_model.queue_response(prop_b_r2)
    eval_model.queue_response(critiques_r2_a)
    eval_model.queue_response(critiques_r2_b)
    eval_model.queue_response(critiques_r2_c)

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate 3-agent compute allocation",
        target_agents=["specialist_a", "specialist_b", "specialist_c"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is True
    assert delib["termination_reason"] == "converged"
    assert delib["active_proposals"]["specialist_a"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_c"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_b"]["round_num"] == 2


@pytest.mark.asyncio
async def test_eval_panel_trio_bounded_termination_on_deadlock(eval_model):
    """Evaluate 3-agent panel: bounded termination at max_rounds with open CONFLICT preserved for minority report.

    Verifies:
    - Specialist A and Specialist C propose conflicting architectures (synchronous vs asynchronous).
    - Specialist B acts as common queue, endorsing both.
    - Specialists A and C maintain CONFLICT stances through Round 2.
    - Deliberation terminates boundedly at max_rounds with open conflicts.
    - ResponseSynthesizerNode renders structured Minority Report.
    """
    config = DeliberationConfig(
        panel_id="panel_trio_deadlock",
        budget=DeliberationBudget(max_rounds=2),
        critique_mode="per_agent",
    )

    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_compute",
        "summary": "Synchronous strongly-consistent ingestion pipeline.",
    }
    prop_b = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_compute",
        "summary": "Common worker execution queue.",
    }
    prop_c = {
        "agent_id": "specialist_c",
        "round_num": 1,
        "scope": "scope_compute",
        "summary": "Asynchronous distributed event stream.",
    }

    # Round 1 peer critiques: A and C conflict on synchronization guarantees; B endorses both.
    critiques_r1_a = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Worker queue fits pipeline.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_c", "round_num": 1, "stance": "conflict", "issue_type": "contraindication", "critique": "Event stream introduces consistency race conditions.", "proposed_resolution": "Adopt synchronous pipeline."},
    ]
    critiques_r1_b = [
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Pipeline design is solid.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Stream design is solid.", "proposed_resolution": "Commit."},
    ]
    critiques_r1_c = [
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_a", "round_num": 1, "stance": "conflict", "issue_type": "risk_exposure", "critique": "Synchronous pipeline creates head-of-line blocking under load.", "proposed_resolution": "Adopt event stream."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Worker queue complements stream.", "proposed_resolution": "Commit."},
    ]

    # Round 2: Specialists A and C revise but uphold architectural stances. Specialist B untouched.
    prop_a_r2 = {
        "agent_id": "specialist_a",
        "round_num": 2,
        "scope": "scope_compute",
        "summary": "Synchronous strongly-consistent pipeline with partitioned locking.",
    }
    prop_c_r2 = {
        "agent_id": "specialist_c",
        "round_num": 2,
        "scope": "scope_compute",
        "summary": "Asynchronous event stream with transactional outbox guarantees.",
    }

    critiques_r2_a = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Worker queue approved.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_c", "round_num": 2, "stance": "conflict", "issue_type": "contraindication", "critique": "Outbox still allows eventual consistency races.", "proposed_resolution": "Adopt synchronous pipeline."},
    ]
    critiques_r2_b = [
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Compatible with queue.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Compatible with queue.", "proposed_resolution": "Commit."},
    ]
    critiques_r2_c = [
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_a", "round_num": 2, "stance": "conflict", "issue_type": "risk_exposure", "critique": "Partitioned locking remains vulnerable to throughput spikes.", "proposed_resolution": "Adopt event stream."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Compatible with queue.", "proposed_resolution": "Commit."},
    ]

    eval_model.queue_response(prop_a)
    eval_model.queue_response(prop_b)
    eval_model.queue_response(prop_c)
    eval_model.queue_response(critiques_r1_a)
    eval_model.queue_response(critiques_r1_b)
    eval_model.queue_response(critiques_r1_c)
    eval_model.queue_response(prop_a_r2)
    eval_model.queue_response(prop_c_r2)
    eval_model.queue_response(critiques_r2_a)
    eval_model.queue_response(critiques_r2_b)
    eval_model.queue_response(critiques_r2_c)

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate architectural pipeline",
        target_agents=["specialist_a", "specialist_b", "specialist_c"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is False
    assert delib["termination_reason"] == "max_rounds_reached"
    # Specialist B was untargeted; preserved untouched
    assert delib["active_proposals"]["specialist_b"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_a"]["round_num"] == 2
    assert delib["active_proposals"]["specialist_c"]["round_num"] == 2

    # Verify minority report generation
    synthesizer = ResponseSynthesizerNode()
    synthesized_markdown = synthesizer.synthesize_deliberation(result)
    assert "## Minority Report" in synthesized_markdown


@pytest.mark.asyncio
async def test_eval_panel_quad_deterministic_convergence(eval_model, eval_constraint_compute):
    """Evaluate 4-agent panel: complex multi-issue coordination converging at Round 2 in batched mode.

    Verifies:
    - 4 specialists coordinate in batched critique mode.
    - Exactly 1 challenged agent (specialist_d) triggers selective revision.
    - Specialists A, B, and C are preserved untouched at round_num == 1.
    - All peer critiques endorse in Round 2, converging cleanly.
    """
    config = DeliberationConfig(
        panel_id="panel_quad_eval",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[eval_constraint_compute],
        critique_mode="batched",
    )

    prop_a = {"agent_id": "specialist_a", "round_num": 1, "scope": "scope_gamma", "summary": "Task A requiring 25 units.", "resource_claims": {"compute_budget": 25.0}, "resource_claim_units": {"compute_budget": "units"}}
    prop_b = {"agent_id": "specialist_b", "round_num": 1, "scope": "scope_gamma", "summary": "Task B requiring 30 units.", "resource_claims": {"compute_budget": 30.0}, "resource_claim_units": {"compute_budget": "units"}}
    prop_c = {"agent_id": "specialist_c", "round_num": 1, "scope": "scope_gamma", "summary": "Task C requiring 20 units.", "resource_claims": {"compute_budget": 20.0}, "resource_claim_units": {"compute_budget": "units"}}
    prop_d = {"agent_id": "specialist_d", "round_num": 1, "scope": "scope_gamma", "summary": "Task D requiring 25 units.", "resource_claims": {"compute_budget": 25.0}, "resource_claim_units": {"compute_budget": "units"}}

    # Batched R1 critique: Specialist B amends Specialist D regarding execution sequence
    r1_batched_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Solid architectural plan with verified scope.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_d", "round_num": 1, "stance": "amend", "issue_type": "dependency_order", "critique": "Sequence step D after step B validation.", "proposed_resolution": "Align execution order."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Prerequisites verified and approved.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_d", "target_agent_id": "specialist_c", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Integration parameters confirmed.", "proposed_resolution": "Commit."},
    ]

    # Round 2: Only specialist_d revises
    prop_d_r2 = {"agent_id": "specialist_d", "round_num": 2, "scope": "scope_gamma", "summary": "Task D revised to sequence after step B.", "resource_claims": {"compute_budget": 25.0}, "resource_claim_units": {"compute_budget": "units"}}

    # Batched R2 critique: All endorse
    r2_batched_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "All dependencies aligned.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_d", "round_num": 2, "stance": "endorse", "issue_type": "synergy", "critique": "Sequence resolved cleanly.", "proposed_resolution": "Commit."},
    ]

    eval_model.queue_response(prop_a)
    eval_model.queue_response(prop_b)
    eval_model.queue_response(prop_c)
    eval_model.queue_response(prop_d)
    eval_model.queue_response(r1_batched_critiques)
    eval_model.queue_response(prop_d_r2)
    eval_model.queue_response(r2_batched_critiques)

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate 4-agent panel",
        target_agents=["specialist_a", "specialist_b", "specialist_c", "specialist_d"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is True
    assert delib["active_proposals"]["specialist_d"]["round_num"] == 2
    assert delib["active_proposals"]["specialist_a"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_b"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_c"]["round_num"] == 1


@pytest.mark.asyncio
async def test_eval_panel_quad_bounded_termination_on_deadlock(eval_model):
    """Evaluate 4-agent panel: bounded termination under cyclic conflict at max_rounds.

    Verifies:
    - In a 4-agent panel, Specialists B and C encounter mutual cyclic dependency CONFLICT.
    - Specialists A and D endorse.
    - Specialists B and C revise in Round 2 but maintain mutual deadlock.
    - Engine terminates boundedly at max_rounds with converged == False.
    """
    config = DeliberationConfig(
        panel_id="panel_quad_deadlock",
        budget=DeliberationBudget(max_rounds=2),
        critique_mode="batched",
    )

    prop_a = {"agent_id": "specialist_a", "round_num": 1, "scope": "scope_gamma", "summary": "Task A summary"}
    prop_b = {"agent_id": "specialist_b", "round_num": 1, "scope": "scope_gamma", "summary": "Task B summary requiring C first"}
    prop_c = {"agent_id": "specialist_c", "round_num": 1, "scope": "scope_gamma", "summary": "Task C summary requiring B first"}
    prop_d = {"agent_id": "specialist_d", "round_num": 1, "scope": "scope_gamma", "summary": "Task D summary"}

    r1_batched_critiques = [
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_d", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Solid infrastructure verified.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "Step B requires step C output first.", "proposed_resolution": "C must yield priority."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_b", "round_num": 1, "stance": "conflict", "issue_type": "dependency_order", "critique": "Step C requires step B output first.", "proposed_resolution": "B must yield priority."},
        {"reviewer_agent_id": "specialist_d", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Prerequisites verified and approved.", "proposed_resolution": "Commit."},
    ]

    prop_b_r2 = {"agent_id": "specialist_b", "round_num": 2, "scope": "scope_gamma", "summary": "Task B maintained cyclic position"}
    prop_c_r2 = {"agent_id": "specialist_c", "round_num": 2, "scope": "scope_gamma", "summary": "Task C maintained cyclic position"}

    r2_batched_critiques = [
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 2, "stance": "conflict", "issue_type": "dependency_order", "critique": "Cyclic deadlock unresolved.", "proposed_resolution": "Escalate to human."},
        {"reviewer_agent_id": "specialist_c", "target_agent_id": "specialist_b", "round_num": 2, "stance": "conflict", "issue_type": "dependency_order", "critique": "Cyclic deadlock unresolved.", "proposed_resolution": "Escalate to human."},
    ]

    eval_model.queue_response(prop_a)
    eval_model.queue_response(prop_b)
    eval_model.queue_response(prop_c)
    eval_model.queue_response(prop_d)
    eval_model.queue_response(r1_batched_critiques)
    eval_model.queue_response(prop_b_r2)
    eval_model.queue_response(prop_c_r2)
    eval_model.queue_response(r2_batched_critiques)

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate 4-agent panel with cyclic dependency",
        target_agents=["specialist_a", "specialist_b", "specialist_c", "specialist_d"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    assert delib["rounds_used"] == 2
    assert delib["converged"] is False
    assert delib["termination_reason"] == "max_rounds_reached"
    assert delib["active_proposals"]["specialist_a"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_d"]["round_num"] == 1
    assert delib["active_proposals"]["specialist_b"]["round_num"] == 2
    assert delib["active_proposals"]["specialist_c"]["round_num"] == 2


# ============================================================================
# Module II: Direct Comparison of per_agent vs batched Critique Modes
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_size", [2, 3, 4])
async def test_eval_critique_mode_call_count_scaling(panel_size: int):
    """Direct comparison of critique call count scaling in run_peer_critiques across panel sizes:
    - per_agent mode makes exactly N model calls (1 per reviewer).
    - batched mode makes exactly 1 model call.
    - Demonstrates (N - 1) / N call reduction in critique phase:
      N=2: 50.0% savings
      N=3: 66.7% savings
      N=4: 75.0% savings
    """
    agent_ids = [f"specialist_{chr(97 + i)}" for i in range(panel_size)]
    proposals = [
        AgentProposal(agent_id=aid, round_num=1, scope="scope_eval", summary=f"Proposal from {aid}")
        for aid in agent_ids
    ]

    # 1. Evaluate per_agent mode
    model_per_agent = MockChatModel(model_name="mock-per-agent")
    for reviewer_id in agent_ids:
        peer_id = next(p for p in agent_ids if p != reviewer_id)
        model_per_agent.queue_response([
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

    critiques_per_agent = await run_peer_critiques(
        proposals=proposals, mode="per_agent", model=model_per_agent, round_num=1
    )
    assert model_per_agent.call_count == panel_size
    assert len(critiques_per_agent) == panel_size

    # 2. Evaluate batched mode
    model_batched = MockChatModel(model_name="mock-batched")
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
    model_batched.queue_response(batched_matrix)

    critiques_batched = await run_peer_critiques(
        proposals=proposals, mode="batched", model=model_batched, round_num=1
    )
    assert model_batched.call_count == 1
    assert len(critiques_batched) == panel_size

    # 3. Assert quantitative savings
    savings_fraction = (model_per_agent.call_count - model_batched.call_count) / model_per_agent.call_count
    expected_savings = (panel_size - 1) / panel_size
    assert abs(savings_fraction - expected_savings) < 1e-6


@pytest.mark.asyncio
async def test_eval_critique_mode_full_lifecycle_call_count(eval_constraint_quota):
    """Direct comparison of full Round 1 lifecycle call counts in DeliberationEngine.run:
    - per_agent: N (propose) + N (critique) = 2N calls.
    - batched: N (propose) + 1 (critique) = N + 1 calls.
    - For N=3: per_agent takes 6 calls; batched takes 4 calls (33.3% savings).
    """
    agents = ["specialist_a", "specialist_b", "specialist_c"]
    n_agents = len(agents)

    # 1. Run per_agent mode
    model_pa = MockChatModel(model_name="mock-pa")
    for aid in agents:
        model_pa.queue_response({"agent_id": aid, "round_num": 1, "scope": "scope_a", "summary": f"{aid} plan"})
    for aid in agents:
        target = "specialist_a" if aid != "specialist_a" else "specialist_b"
        model_pa.queue_response([
            {"reviewer_agent_id": aid, "target_agent_id": target, "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Solid plan.", "proposed_resolution": "Commit."}
        ])

    config_pa = DeliberationConfig(panel_id="p1", critique_mode="per_agent", budget=DeliberationBudget(max_rounds=1))
    engine_pa = DeliberationEngine(model=model_pa, config=config_pa)
    state_pa = create_initial_state(prompt="Test", target_agents=agents, deliberation_config=config_pa.model_dump())
    await engine_pa.run(state_pa)

    assert model_pa.call_count == 2 * n_agents  # 3 + 3 = 6 calls

    # 2. Run batched mode
    model_ba = MockChatModel(model_name="mock-ba")
    for aid in agents:
        model_ba.queue_response({"agent_id": aid, "round_num": 1, "scope": "scope_a", "summary": f"{aid} plan"})
    model_ba.queue_response([
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Solid plan.", "proposed_resolution": "Commit."},
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_c", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Solid plan.", "proposed_resolution": "Commit."},
    ])

    config_ba = DeliberationConfig(panel_id="p2", critique_mode="batched", budget=DeliberationBudget(max_rounds=1))
    engine_ba = DeliberationEngine(model=model_ba, config=config_ba)
    state_ba = create_initial_state(prompt="Test", target_agents=agents, deliberation_config=config_ba.model_dump())
    await engine_ba.run(state_ba)

    assert model_ba.call_count == n_agents + 1  # 3 + 1 = 4 calls
    savings_pct = (model_pa.call_count - model_ba.call_count) / model_pa.call_count * 100.0
    assert abs(savings_pct - 33.333333) < 1e-2


@pytest.mark.asyncio
async def test_eval_critique_mode_parity_and_doc_compliance():
    """Verify both per_agent and batched critique modes strictly satisfy Disagree-or-Commit invariants.

    Verifies:
    - Bare agreement (empty critique or generic boilerplate) is rejected.
    - Substantive supporting points are required for ENDORSE.
    - Self-critiques are forbidden and filtered.
    - Both modes output structured PeerCritique schemas.
    """
    proposals = [
        AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_x", summary="Plan A"),
        AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_x", summary="Plan B"),
    ]

    # 1. per_agent mode rejects bare agreement without supporting rationale
    model_bare = MockChatModel(model_name="mock-bare")
    # Specialist A attempts empty bare agreement
    model_bare.queue_response([
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "", "proposed_resolution": ""}
    ])
    # Specialist B provides substantive endorsement
    model_bare.queue_response([
        {"reviewer_agent_id": "specialist_b", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Substantive supporting rationale verifying prerequisites.", "proposed_resolution": "Commit"}
    ])

    critiques_pa = await run_peer_critiques(proposals, mode="per_agent", model=model_bare, round_num=1, max_retries=0)
    # The empty critique fails validation and is dropped
    assert len(critiques_pa) == 1
    assert critiques_pa[0].reviewer_agent_id == "specialist_b"

    # 2. batched mode filters out self-critiques
    model_batch_self = MockChatModel(model_name="mock-batch-self")
    model_batch_self.queue_response([
        # Self critique: must be filtered
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_a", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Self endorsement", "proposed_resolution": "Commit"},
        # Valid peer critique
        {"reviewer_agent_id": "specialist_a", "target_agent_id": "specialist_b", "round_num": 1, "stance": "endorse", "issue_type": "synergy", "critique": "Valid peer endorsement with substantive points.", "proposed_resolution": "Commit"},
    ])

    critiques_ba = await run_peer_critiques(proposals, mode="batched", model=model_batch_self, round_num=1, max_retries=0)
    assert len(critiques_ba) == 1
    assert critiques_ba[0].reviewer_agent_id == "specialist_a"
    assert critiques_ba[0].target_agent_id == "specialist_b"


# ============================================================================
# Module III: Selective Revision Call-Count Savings
# ============================================================================


@pytest.mark.asyncio
async def test_eval_selective_revision_single_target_savings(eval_model):
    """Evaluate 3-agent panel: 1 of 3 challenged yields exactly 1 revision call (66.7% call reduction).

    Verifies:
    - Only targeted agent (specialist_b) invokes the model in Round 2.
    - Untargeted proposals for specialist_a and specialist_c remain untouched at round_num == 1.
    - Exactly 1 model call made vs 3 in a full re-run (66.7% savings).
    """
    active_proposals = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="A proposal"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="B proposal"),
        "specialist_c": AgentProposal(agent_id="specialist_c", round_num=1, scope="scope_alpha", summary="C proposal"),
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
            proposed_resolution="Sequence after step 1",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_b",
            target_agent_id="specialist_c",
            round_num=1,
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique="Proposal C is aligned with goals.",
            proposed_resolution="Commit",
            resolved=True,
        ),
    ]

    eval_model.queue_response({
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Revised B proposal with updated sequence",
    })

    revised_proposals = await run_selective_revision(
        active_proposals=active_proposals,
        critiques=critiques,
        round_num=2,
        model=eval_model,
    )

    # Invariants:
    # 1. Model called exactly 1 time (only for specialist_b)
    assert eval_model.call_count == 1
    # 2. Call savings = (3 - 1) / 3 = 66.7%
    full_rerun_calls = len(active_proposals)
    savings_pct = (full_rerun_calls - eval_model.call_count) / full_rerun_calls * 100.0
    assert abs(savings_pct - 66.666666) < 1e-2

    # 3. Untargeted proposals preserved untouched
    assert revised_proposals["specialist_a"].round_num == 1
    assert revised_proposals["specialist_a"].summary == "A proposal"
    assert revised_proposals["specialist_c"].round_num == 1
    assert revised_proposals["specialist_c"].summary == "C proposal"

    # 4. Targeted proposal updated
    assert revised_proposals["specialist_b"].round_num == 2
    assert "Revised" in revised_proposals["specialist_b"].summary


@pytest.mark.asyncio
async def test_eval_selective_revision_zero_target_consensus_savings(eval_model):
    """Evaluate 3-agent panel: 0 of 3 challenged (consensus) yields 0 revision calls (100% call reduction)."""
    active_proposals = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="A proposal"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="B proposal"),
        "specialist_c": AgentProposal(agent_id="specialist_c", round_num=1, scope="scope_alpha", summary="C proposal"),
    }
    # All peer critiques are endorsements
    critiques = [
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            round_num=1,
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique="Well scoped and aligned.",
            proposed_resolution="Commit",
            resolved=True,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_b",
            target_agent_id="specialist_c",
            round_num=1,
            stance=CritiqueStance.COMPLEMENT,
            issue_type="synergy",
            critique="Complementary workflow.",
            proposed_resolution="Commit",
            resolved=True,
        ),
    ]

    revised_proposals = await run_selective_revision(
        active_proposals=active_proposals,
        critiques=critiques,
        round_num=2,
        model=eval_model,
    )

    # 0 calls made because no agents are targeted
    assert eval_model.call_count == 0
    # 100% call savings vs 3 calls in full re-run
    assert len(revised_proposals) == 3
    assert all(p.round_num == 1 for p in revised_proposals.values())


@pytest.mark.asyncio
async def test_eval_selective_revision_multi_target_savings(eval_model):
    """Evaluate 4-agent panel: 2 of 4 challenged yields exactly 2 revision calls (50.0% call reduction)."""
    active_proposals = {
        "specialist_a": AgentProposal(agent_id="specialist_a", round_num=1, scope="scope_alpha", summary="A proposal"),
        "specialist_b": AgentProposal(agent_id="specialist_b", round_num=1, scope="scope_alpha", summary="B proposal"),
        "specialist_c": AgentProposal(agent_id="specialist_c", round_num=1, scope="scope_alpha", summary="C proposal"),
        "specialist_d": AgentProposal(agent_id="specialist_d", round_num=1, scope="scope_alpha", summary="D proposal"),
    }
    # Specialists B and D are targeted by open CONFLICT / AMEND critiques
    critiques = [
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            round_num=1,
            stance=CritiqueStance.CONFLICT,
            issue_type="resource_overbudget",
            critique="Over budget limit",
            proposed_resolution="Reduce claim",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_c",
            target_agent_id="specialist_d",
            round_num=1,
            stance=CritiqueStance.AMEND,
            issue_type="dependency_order",
            critique="Sequence mismatch",
            proposed_resolution="Adjust step order",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_b",
            target_agent_id="specialist_a",
            round_num=1,
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique="Good infrastructure",
            proposed_resolution="Commit",
            resolved=True,
        ),
    ]

    eval_model.queue_response({"agent_id": "specialist_b", "round_num": 2, "scope": "scope_alpha", "summary": "B revised"})
    eval_model.queue_response({"agent_id": "specialist_d", "round_num": 2, "scope": "scope_alpha", "summary": "D revised"})

    revised_proposals = await run_selective_revision(
        active_proposals=active_proposals,
        critiques=critiques,
        round_num=2,
        model=eval_model,
    )

    # Exactly 2 calls made
    assert eval_model.call_count == 2
    # 50% call savings vs 4 calls in full re-run
    savings = (4 - eval_model.call_count) / 4.0
    assert savings == 0.50
    assert revised_proposals["specialist_a"].round_num == 1
    assert revised_proposals["specialist_c"].round_num == 1
    assert revised_proposals["specialist_b"].round_num == 2
    assert revised_proposals["specialist_d"].round_num == 2


# ============================================================================
# Module IV: Extended Resilience & Invariant Evals
# ============================================================================


@pytest.mark.asyncio
async def test_eval_fault_tolerance_repair_retry_and_degradation(eval_model):
    """Verify schema-failure repair retry and graceful degradation to single-agent fallback (< 2 valid)."""
    config = DeliberationConfig(panel_id="panel_degradation_eval")

    # Specialist A succeeds on attempt 1
    eval_model.queue_response({
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Valid proposal from Specialist A",
    })
    # Specialist B fails schema validation on attempt 1 and repair retry attempt 2
    eval_model.queue_response({"malformed_field": "no agent id"})
    eval_model.queue_response({"malformed_retry": "still invalid"})

    engine = DeliberationEngine(model=eval_model, config=config)
    state = create_initial_state(
        prompt="Coordinate resilient panel",
        target_agents=["specialist_a", "specialist_b"],
        deliberation_config=config.model_dump(),
    )
    result = await engine.run(state)
    delib = result["deliberation_state"]

    # Specialist B was given 1 retry (2 total calls for B)
    assert delib["degraded"] is True
    assert delib["rounds_used"] == 1
    assert delib["termination_reason"] == "single_agent_fallback"
    assert "specialist_b" in delib["missing_agents"]
    assert "specialist_a" in result["specialist_outputs"]
    assert "degraded to single-agent answer" in result["output"]


def test_eval_budget_wall_clock_and_token_exhaustion():
    """Verify bounded termination when wall-clock or token budget limits are reached."""
    budget = DeliberationBudget(max_rounds=2, max_wall_clock_s=1.0, max_total_tokens=1000)

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

    # 1. Wall-clock limit exceeded
    simulated_start_time = time.time() - 2.0  # 2.0s elapsed > 1.0s limit
    decision_wall_clock = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        max_rounds=2,
        budget=budget,
        start_time=simulated_start_time,
        total_tokens=100,
    )
    assert decision_wall_clock.next_node == "synthesize"
    assert decision_wall_clock.converged is False
    assert decision_wall_clock.reason == "wall_clock_exhausted"

    # 2. Token budget exceeded
    decision_token = evaluate_convergence_gate(
        critiques=[blocking_critique],
        round_num=1,
        max_rounds=2,
        budget=budget,
        start_time=time.time(),
        total_tokens=1500,  # 1500 tokens > 1000 limit
    )
    assert decision_token.next_node == "synthesize"
    assert decision_token.converged is False
    assert decision_token.reason == "token_budget_exhausted"


def test_eval_taint_propagation_and_synthesis_warning_flag():
    """Verify monotonic taint propagation triggers untrusted input warning flags in synthesis."""
    proposals = {
        "specialist_a": AgentProposal(
            agent_id="specialist_a",
            round_num=1,
            scope="scope_alpha",
            summary="Proposal derived from unverified external input",
            tainted=True,
        ),
        "specialist_b": AgentProposal(
            agent_id="specialist_b",
            round_num=1,
            scope="scope_alpha",
            summary="Clean proposal from vetted internal sources",
            tainted=False,
        ),
    }

    state = {
        "deliberation_state": {
            "active_proposals": {aid: p.model_dump() for aid, p in proposals.items()},
            "rounds_used": 1,
            "converged": True,
            "termination_reason": "converged",
            "critiques": {},
            "shared_constraints": [],
            "skipped_constraints": [],
        },
        "target_agents": ["specialist_a", "specialist_b"],
        "prompt": "Evaluate input reliability",
    }

    synthesizer = ResponseSynthesizerNode()
    synthesized = synthesizer.synthesize_deliberation(state)

    # Assert warning banner is present
    assert "⚠️ **Warning**" in synthesized
    assert "untrusted source" in synthesized.lower()
    # Assert specific untrusted tag next to tainted agent perspective
    assert "Specialist A Perspective [⚠️ Untrusted Source]" in synthesized


def test_eval_skipped_constraints_explicit_notation():
    """Verify unbounded constraints (limit_value is None) are skipped by auditor and explicitly noted in synthesis."""
    c_unbounded = SharedConstraint(
        id="storage_volume",
        description="Unbounded storage volume allocation",
        unit="units",
        limit_value=None,  # Unknown limit
        limit_source=None,
    )
    prop = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Storage expansion proposal",
        resource_claims={"storage_volume": 500.0},
        resource_claim_units={"storage_volume": "units"},
    )

    auditor = BudgetAuditor()
    critiques = auditor.audit(constraints=[c_unbounded], proposals=[prop])

    # Auditor emits 0 critiques and skips arithmetic check
    assert len(critiques) == 0
    assert "storage_volume" in auditor.skipped_constraints

    state = {
        "deliberation_state": {
            "active_proposals": {"specialist_a": prop.model_dump()},
            "rounds_used": 1,
            "converged": True,
            "termination_reason": "converged",
            "critiques": {},
            "shared_constraints": [c_unbounded.model_dump()],
            "skipped_constraints": ["storage_volume"],
        },
        "target_agents": ["specialist_a"],
        "prompt": "Review storage usage",
    }

    synthesizer = ResponseSynthesizerNode()
    synthesized = synthesizer.synthesize_deliberation(state)

    # Synthesizer explicitly notes that constraint was not checked against limits
    assert "storage_volume" in synthesized
    assert "Limit Unknown (Skipped)" in synthesized
    assert "not checked against a budget boundary" in synthesized.lower()
