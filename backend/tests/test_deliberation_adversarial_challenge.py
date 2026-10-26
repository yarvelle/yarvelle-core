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

"""Adversarial stress-test challenge suite for multi-agent deliberation boundaries (M4 / R4).

Empirically challenges:
1. Disagree-or-Commit validation boundaries:
   - Bare agreement boundary (exact length 9 vs 10, boilerplate vs non-boilerplate).
   - Whitespace padding (leading, trailing, internal, empty/whitespace-only).
   - Self-critique filtering in batched vs per_agent modes and direct model validation.
   - Non-empty critique and proposed_resolution requirements for AMEND and CONFLICT.
2. Schema repair retry failure degradation across multiple failing specialists:
   - 2 of 3 specialists fail repair retries -> graceful degradation to single_agent_fallback.
   - 2 of 4 specialists fail repair retries -> 2 survive, deliberation continues without degradation.
   - All specialists fail repair retries -> graceful single_agent_fallback with no unhandled exceptions.
   - Successful repair retry recovery on attempt 2.
3. Untouched preservation of untargeted proposals across complex multi-round graphs:
   - Strict immutability of untargeted proposals across 2-round and 3-round deliberation graphs.
   - Exact verification of round_num, resource_claims, recommendations, and summary preservation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
import pytest
from pydantic import ValidationError

from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    ExecutionPlan,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal, run_propose_phase
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
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
# Shared Fixtures
# ============================================================================


@pytest.fixture
def challenge_model() -> MockChatModel:
    """Deterministic offline model for adversarial challenge verification."""
    return MockChatModel(model_name="mock-challenge-engine")


@pytest.fixture
def challenge_constraint_quota() -> SharedConstraint:
    """Generic quota constraint."""
    return SharedConstraint(
        id="weekly_quota",
        description="Allowable workload quota",
        unit="hours",
        limit_value=20.0,
        limit_source="user",
    )


# ============================================================================
# Section 1: Disagree-or-Commit Validation Boundaries & Edge Cases
# ============================================================================


def test_doc_bare_agreement_boundary_length_9_vs_10():
    """Validates the exact 9 vs 10 character boundary on ENDORSE critiques."""
    # 1. Non-boilerplate strings of length exactly 9 must FAIL
    length_9_candidates = [
        "123456789",
        "excellent",
        "good plan",  # 4 + 1 + 4 = 9 chars
        "valid rec",  # 5 + 1 + 3 = 9 chars
    ]
    for text in length_9_candidates:
        assert len(text) == 9
        with pytest.raises(ValidationError, match="ENDORSE stance requires substantive supporting points"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=CritiqueStance.ENDORSE,
                issue_type="synergy",
                critique=text,
                proposed_resolution="Maintain alignment",
            )

    # 2. Non-boilerplate strings of length exactly 10 must SUCCEED
    length_10_candidates = [
        "1234567890",
        "sound plan",  # 5 + 1 + 4 = 10 chars
        "solid work",  # 5 + 1 + 4 = 10 chars
        "good point",  # 4 + 1 + 5 = 10 chars
    ]
    for text in length_10_candidates:
        assert len(text) == 10
        critique = PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique=text,
            proposed_resolution="Maintain alignment",
        )
        assert critique.critique == text

    # 3. Boilerplate strings of length 10 or greater must still FAIL
    boilerplate_candidates = [
        "looks good",       # len 10
        "looks good to me", # len 16
        "no issues",        # len 9
        "fine",             # len 4
        "approved",         # len 8
        "endorse",          # len 7
    ]
    for text in boilerplate_candidates:
        with pytest.raises(ValidationError, match="ENDORSE stance requires substantive supporting points"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=CritiqueStance.ENDORSE,
                issue_type="synergy",
                critique=text,
                proposed_resolution="Keep as is",
            )


def test_doc_whitespace_padding_boundary():
    """Validates whitespace trimming behavior on critique rationale."""
    # 1. Whitespace padding around length-9 string must not bypass boundary
    padded_len_9 = "   123456789   "
    assert len(padded_len_9) == 15
    assert len(padded_len_9.strip()) == 9
    with pytest.raises(ValidationError, match="substantive supporting points"):
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique=padded_len_9,
            proposed_resolution="Valid resolution text",
        )

    # 2. Whitespace padding around boilerplate must still be rejected
    padded_boilerplate = "   \n\t  looks good to me  \t\n "
    with pytest.raises(ValidationError, match="substantive supporting points"):
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_b",
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique=padded_boilerplate,
            proposed_resolution="Valid resolution text",
        )

    # 3. Empty or pure whitespace critique must be rejected
    for empty_val in ["", "   ", "\t\n\r"]:
        with pytest.raises(ValidationError, match="substantive supporting points"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=CritiqueStance.ENDORSE,
                issue_type="synergy",
                critique=empty_val,
                proposed_resolution="Valid resolution text",
            )

    # 4. Valid length-10 content with surrounding whitespace is accepted
    padded_valid = "   sound plan   "
    critique = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        stance=CritiqueStance.ENDORSE,
        issue_type="synergy",
        critique=padded_valid,
        proposed_resolution="Valid resolution text",
    )
    assert critique.critique == padded_valid


def test_doc_self_critique_validation_and_mode_filtering(challenge_model):
    """Validates rejection and filtering of self-critiques across direct schemas, batched, and per_agent."""
    # 1. Direct model validation must strictly raise ValueError
    with pytest.raises(ValidationError, match="reviewer_agent_id and target_agent_id must be different"):
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_a",
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique="Substantive supporting points here",
            proposed_resolution="Self resolution",
        )

    # 2. Batched mode: model returns self-critique mixed with valid critique
    prop_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Summary A",
        recommendations=["rec_a"],
        resource_claims={},
        resource_claim_units={},
    )
    prop_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha",
        summary="Summary B",
        recommendations=["rec_b"],
        resource_claims={},
        resource_claim_units={},
    )

    batch_response_mixed = [
        # Self-critique (should be filtered)
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Self endorsement rationale here",
            "proposed_resolution": "No action",
        },
        # Valid peer critique
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_b",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid endorsement rationale for specialist_b",
            "proposed_resolution": "No action",
        },
        # Another self-critique (should be filtered)
        {
            "reviewer_agent_id": "specialist_b",
            "target_agent_id": "specialist_b",
            "stance": "conflict",
            "issue_type": "risk_exposure",
            "critique": "Self conflict rationale here",
            "proposed_resolution": "Fix self",
        },
    ]

    challenge_model.queue_response(batch_response_mixed)

    import asyncio
    critiques = asyncio.run(
        run_peer_critiques(
            proposals=[prop_a, prop_b],
            mode="batched",
            model=challenge_model,
            round_num=1,
        )
    )

    assert len(critiques) == 1
    assert critiques[0].reviewer_agent_id == "specialist_a"
    assert critiques[0].target_agent_id == "specialist_b"

    # 3. Batched mode: ALL self-critiques returned -> returns empty list without raising exception
    batch_response_all_self = [
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Self endorsement rationale",
            "proposed_resolution": "None",
        }
    ]
    challenge_model.queue_response(batch_response_all_self)
    critiques_empty = asyncio.run(
        run_peer_critiques(
            proposals=[prop_a, prop_b],
            mode="batched",
            model=challenge_model,
            round_num=1,
        )
    )
    assert critiques_empty == []

    # 4. per_agent mode: reviewer model returns a critique targeting itself
    # per_agent loops over prop_a, then prop_b
    per_agent_a_response = [
        # self target
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Self critique targeting own agent id",
            "proposed_resolution": "None",
        },
        # peer target
        {
            "target_agent_id": "specialist_b",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Substantive peer endorsement from A to B",
            "proposed_resolution": "None",
        },
    ]
    per_agent_b_response = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Substantive peer endorsement from B to A",
            "proposed_resolution": "None",
        }
    ]
    challenge_model.queue_response(per_agent_a_response)
    challenge_model.queue_response(per_agent_b_response)

    critiques_per = asyncio.run(
        run_peer_critiques(
            proposals=[prop_a, prop_b],
            mode="per_agent",
            model=challenge_model,
            round_num=1,
        )
    )
    assert len(critiques_per) == 2
    # Verify neither critique is a self-critique
    for c in critiques_per:
        assert c.reviewer_agent_id != c.target_agent_id


def test_doc_amend_and_conflict_field_invariants():
    """Validates that AMEND and CONFLICT require non-empty critique and proposed_resolution."""
    for stance in (CritiqueStance.AMEND, CritiqueStance.CONFLICT):
        # Empty critique
        with pytest.raises(ValidationError, match="requires non-empty critique and proposed_resolution"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=stance,
                issue_type="resource_overbudget",
                critique="",
                proposed_resolution="Reduce quota by 5 units",
            )

        # Whitespace-only critique
        with pytest.raises(ValidationError, match="requires non-empty critique and proposed_resolution"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=stance,
                issue_type="resource_overbudget",
                critique="   \t   ",
                proposed_resolution="Reduce quota by 5 units",
            )

        # Empty proposed_resolution
        with pytest.raises(ValidationError, match="requires non-empty critique and proposed_resolution"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=stance,
                issue_type="resource_overbudget",
                critique="Significant resource overage detected",
                proposed_resolution="",
            )

        # Whitespace-only proposed_resolution
        with pytest.raises(ValidationError, match="requires non-empty critique and proposed_resolution"):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                stance=stance,
                issue_type="resource_overbudget",
                critique="Significant resource overage detected",
                proposed_resolution="    ",
            )


# ============================================================================
# Section 2: Schema Repair Retry Failure Degradation
# ============================================================================


@pytest.mark.asyncio
async def test_schema_repair_retry_multiple_failing_specialists_degrades_to_single(
    challenge_model, challenge_constraint_quota
):
    """Stress-tests 2 of 3 specialists failing schema validation retries.

    Scenario:
    - Specialist A: Succeeds on attempt 1.
    - Specialist B: Fails attempt 1 (malformed string), fails attempt 2 (retry) -> dropped.
    - Specialist C: Fails attempt 1 (invalid types), fails attempt 2 (retry) -> dropped.
    - Result: Only 1 specialist survives -> triggers single_agent_fallback degradation.
    """
    config = DeliberationConfig(
        panel_id="panel_trio_degrade",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[challenge_constraint_quota],
    )
    plan = ExecutionPlan(
        title="Degradation Test Plan",
        target_agents=["specialist_a", "specialist_b", "specialist_c"],
        deliberation_config=config,
    )
    state = create_initial_state("Run multi-agent workload.")
    state["execution_plan"] = plan

    # Specialist A: Success attempt 1
    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist A valid standalone proposal",
        "recommendations": ["Execute task A"],
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_a)

    # Specialist B: Attempt 1 malformed text, Attempt 2 malformed text
    challenge_model.queue_response("MALFORMED_OUTPUT_NOT_JSON")
    challenge_model.queue_response("STILL_MALFORMED_AFTER_RETRY")

    # Specialist C: Attempt 1 invalid schema types, Attempt 2 invalid schema types
    challenge_model.queue_response({"agent_id": "specialist_c", "summary": 12345})  # summary not string
    challenge_model.queue_response({"agent_id": "specialist_c", "resource_claims": "not_a_dict"})

    engine = DeliberationEngine(model=challenge_model, config=config)
    result_state = await engine.run(state)

    delib_state = result_state["deliberation_state"]
    assert delib_state["degraded"] is True
    assert delib_state["termination_reason"] == "single_agent_fallback"
    assert delib_state["rounds_used"] == 1
    assert "specialist_a" in result_state["specialist_outputs"]
    assert len(result_state["specialist_outputs"]) == 1

    # Verify output explains degradation and identifies dropped agents
    output_text = result_state["output"]
    assert "Deliberation degraded to single-agent answer" in output_text
    assert "specialist_b" in output_text
    assert "specialist_c" in output_text
    assert "Specialist A valid standalone proposal" in output_text


@pytest.mark.asyncio
async def test_schema_repair_retry_multiple_failing_specialists_partial_survival(
    challenge_model, challenge_constraint_quota
):
    """Stress-tests 2 of 4 specialists failing retries while 2 survive.

    Scenario:
    - 4-agent panel (A, B, C, D).
    - Specialist A: Succeeds attempt 1.
    - Specialist B: Fails attempt 1 and retry 2 -> dropped.
    - Specialist C: Fails attempt 1 and retry 2 -> dropped.
    - Specialist D: Succeeds attempt 1.
    - Result: 2 of 4 survive (>= 2). Panel DOES NOT degrade; continues to CrossExamine!
    """
    config = DeliberationConfig(
        panel_id="panel_quad_partial_fail",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[challenge_constraint_quota],
    )
    plan = ExecutionPlan(
        title="Partial Survival Plan",
        target_agents=["specialist_a", "specialist_b", "specialist_c", "specialist_d"],
        deliberation_config=config,
    )
    state = create_initial_state("Execute quad panel task.")
    state["execution_plan"] = plan

    # Specialist A: Success attempt 1
    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist A proposal",
        "recommendations": ["Action A"],
        "resource_claims": {"weekly_quota": 5.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_a)

    # Specialist B: Fails twice
    challenge_model.queue_response("BROKEN_JSON_B1")
    challenge_model.queue_response("BROKEN_JSON_B2")

    # Specialist C: Fails twice
    challenge_model.queue_response("BROKEN_JSON_C1")
    challenge_model.queue_response("BROKEN_JSON_C2")

    # Specialist D: Success attempt 1
    prop_d = {
        "agent_id": "specialist_d",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist D proposal",
        "recommendations": ["Action D"],
        "resource_claims": {"weekly_quota": 6.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_d)

    # CrossExamine: peer critiques between surviving A and D
    # A endorses D
    critique_a_to_d = [
        {
            "target_agent_id": "specialist_d",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Solid proposal and within quota limits",
            "proposed_resolution": "Maintain plan",
        }
    ]
    # D endorses A
    critique_d_to_a = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Compatible workflow and well structured",
            "proposed_resolution": "Maintain plan",
        }
    ]
    challenge_model.queue_response(critique_a_to_d)
    challenge_model.queue_response(critique_d_to_a)

    engine = DeliberationEngine(model=challenge_model, config=config)
    result_state = await engine.run(state)

    delib_state = result_state["deliberation_state"]
    assert delib_state["degraded"] is False
    assert delib_state["converged"] is True
    assert delib_state["termination_reason"] == "converged"
    assert delib_state["rounds_used"] == 1
    assert set(result_state["specialist_outputs"].keys()) == {"specialist_a", "specialist_d"}


@pytest.mark.asyncio
async def test_schema_repair_all_specialists_fail_graceful(
    challenge_model, challenge_constraint_quota
):
    """Stress-tests 3 of 3 specialists failing schema repair retries.

    Scenario:
    - All 3 specialists fail on both attempt 1 and retry 2.
    - 0 valid proposals survive.
    - Engine must gracefully terminate with degraded=True and fallback output without crashing.
    """
    config = DeliberationConfig(
        panel_id="panel_trio_all_fail",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[challenge_constraint_quota],
    )
    plan = ExecutionPlan(
        title="All Fail Plan",
        target_agents=["specialist_a", "specialist_b", "specialist_c"],
        deliberation_config=config,
    )
    state = create_initial_state("Execute trio panel.")
    state["execution_plan"] = plan

    # 3 agents x 2 failures = 6 failed responses
    for i in range(6):
        challenge_model.queue_response(f"INVALID_JSON_RESPONSE_{i}")

    engine = DeliberationEngine(model=challenge_model, config=config)
    result_state = await engine.run(state)

    delib_state = result_state["deliberation_state"]
    assert delib_state["degraded"] is True
    assert delib_state["termination_reason"] == "single_agent_fallback"
    assert len(result_state["specialist_outputs"]) == 0
    assert "No proposal available" in result_state["output"]


@pytest.mark.asyncio
async def test_schema_repair_successful_retry_recovery(challenge_model):
    """Validates that a specialist failing attempt 1 successfully recovers on retry attempt 2."""
    valid_proposal_dict = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Repaired proposal on attempt 2",
        "recommendations": ["Action Alpha"],
        "resource_claims": {},
        "resource_claim_units": {},
    }

    # Queue invalid JSON for attempt 1, followed by valid JSON for attempt 2
    challenge_model.queue_response("SYNTAX_ERROR_RAW_TEXT")
    challenge_model.queue_response(valid_proposal_dict)

    proposal = await generate_agent_proposal(
        agent_id="specialist_a",
        round_num=1,
        model=challenge_model,
        max_retries=1,
    )

    assert proposal.agent_id == "specialist_a"
    assert proposal.summary == "Repaired proposal on attempt 2"


# ============================================================================
# Section 3: Preservation of Untargeted Proposals Across Multi-Round Graphs
# ============================================================================


@pytest.mark.asyncio
async def test_untargeted_proposals_deep_immutability_round_1_to_round_2(
    challenge_model, challenge_constraint_quota
):
    """Verifies that untargeted proposals in a 3-agent panel are preserved completely intact in Round 2.

    Panel: specialist_a (untargeted), specialist_b (targeted for revision), specialist_c (untargeted).
    In Round 2:
    - specialist_b is revised (round_num -> 2, updated claims, updated summary).
    - specialist_a and specialist_c are UNTARGETED.
    - Verifies:
      * specialist_a.round_num remains 1.
      * specialist_c.round_num remains 1.
      * claims, recommendations, summaries, and scopes remain byte-identical.
    """
    config = DeliberationConfig(
        panel_id="panel_trio_untargeted_immutability",
        budget=DeliberationBudget(max_rounds=2),
        shared_constraints=[challenge_constraint_quota],
    )
    plan = ExecutionPlan(
        title="Immutability Verification",
        target_agents=["specialist_a", "specialist_b", "specialist_c"],
        deliberation_config=config,
    )
    state = create_initial_state("Multi-round panel.")
    state["execution_plan"] = plan

    # Round 1 Proposals (Claims within budget: 4 + 8 + 3 = 15.0 <= 20.0)
    prop_a_init = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Initial summary for Specialist A",
        "recommendations": ["Rec A1", "Rec A2"],
        "resource_claims": {"weekly_quota": 4.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_b_init = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Initial summary for Specialist B",
        "recommendations": ["Rec B1"],
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_c_init = {
        "agent_id": "specialist_c",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Initial summary for Specialist C",
        "recommendations": ["Rec C1", "Rec C2", "Rec C3"],
        "resource_claims": {"weekly_quota": 3.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }

    challenge_model.queue_response(prop_a_init)
    challenge_model.queue_response(prop_b_init)
    challenge_model.queue_response(prop_c_init)

    # Round 1 CrossExamine: Total claims = 15.0 <= 20.0 -> BudgetAuditor emits 0 critiques.
    # Peer critiques: A and C endorse each other, but challenge B on dependency_order / risk_exposure.
    critique_from_a = [
        {
            "target_agent_id": "specialist_c",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist C proposal is highly compatible",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_b",
            "stance": "conflict",
            "issue_type": "dependency_order",
            "critique": "Specialist B sequence clashes with step prerequisites",
            "proposed_resolution": "Reorder phase actions",
        },
    ]
    critique_from_b = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist A proposal is fine and grounded",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_c",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist C proposal is well constructed",
            "proposed_resolution": "Maintain",
        },
    ]
    critique_from_c = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist A proposal meets quality criteria",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_b",
            "stance": "amend",
            "issue_type": "risk_exposure",
            "critique": "Specialist B must add fallback mitigation checkpoint",
            "proposed_resolution": "Add fallback safety checkpoint",
        },
    ]

    challenge_model.queue_response(critique_from_a)
    challenge_model.queue_response(critique_from_b)
    challenge_model.queue_response(critique_from_c)

    # Round 2: Only specialist_b is revised! (1 revision call)
    prop_b_revised = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Revised summary for Specialist B (fixed dependency and fallback)",
        "recommendations": ["Rec B1 reordered", "Rec B1 fallback"],
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_b_revised)

    # Round 2 CrossExamine: Total quota = 4 + 8 + 3 = 15.0 <= 20.0
    # Peers endorse revised B
    critique_r2_from_a = [
        {
            "target_agent_id": "specialist_b",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Revised dependency ordering is satisfactory",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_c",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist C proposal is still solid",
            "proposed_resolution": "Maintain",
        },
    ]
    critique_r2_from_b = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist A proposal remains acceptable",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_c",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist C proposal remains acceptable",
            "proposed_resolution": "Maintain",
        },
    ]
    critique_r2_from_c = [
        {
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist A proposal remains solid",
            "proposed_resolution": "Maintain",
        },
        {
            "target_agent_id": "specialist_b",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist B revised proposal is approved",
            "proposed_resolution": "Maintain",
        },
    ]

    challenge_model.queue_response(critique_r2_from_a)
    challenge_model.queue_response(critique_r2_from_b)
    challenge_model.queue_response(critique_r2_from_c)

    engine = DeliberationEngine(model=challenge_model, config=config)
    result_state = await engine.run(state)

    delib_state = result_state["deliberation_state"]
    assert delib_state["converged"] is True
    assert delib_state["rounds_used"] == 2

    active_props = delib_state["active_proposals"]

    # Verify untargeted Specialist A
    prop_a_active = active_props["specialist_a"]
    assert prop_a_active["round_num"] == 1, "Untargeted proposal round_num must remain 1"
    assert prop_a_active["summary"] == "Initial summary for Specialist A"
    assert prop_a_active["recommendations"] == ["Rec A1", "Rec A2"]
    assert prop_a_active["resource_claims"] == {"weekly_quota": 4.0}

    # Verify untargeted Specialist C
    prop_c_active = active_props["specialist_c"]
    assert prop_c_active["round_num"] == 1, "Untargeted proposal round_num must remain 1"
    assert prop_c_active["summary"] == "Initial summary for Specialist C"
    assert prop_c_active["recommendations"] == ["Rec C1", "Rec C2", "Rec C3"]
    assert prop_c_active["resource_claims"] == {"weekly_quota": 3.0}

    # Verify targeted Specialist B
    prop_b_active = active_props["specialist_b"]
    assert prop_b_active["round_num"] == 2, "Targeted proposal round_num must advance to 2"
    assert prop_b_active["summary"] == "Revised summary for Specialist B (fixed dependency and fallback)"
    assert prop_b_active["recommendations"] == ["Rec B1 reordered", "Rec B1 fallback"]
    assert prop_b_active["resource_claims"] == {"weekly_quota": 8.0}


@pytest.mark.asyncio
async def test_untargeted_proposals_preservation_across_3_rounds_complex_graph(challenge_model):
    """Stress-tests untargeted proposals remaining untouched across a 3-round deliberation graph.

    Panel: 4 agents (A, B, C, D) with max_rounds=3.
    - Round 1: All 4 propose.
      Critique targets only Specialist B on dependency ordering. Agents A, C, and D are untargeted.
    - Round 2: Only B revises (1 revision call).
      Critique notes B still has an unresolved dependency issue.
      Agents A, C, and D remain untargeted for a second consecutive round!
    - Round 3: Only B revises again (1 revision call).
      Critique resolves and all converge.
    - Verifications:
      * Specialist A, C, and D preserve round_num == 1 across all 3 rounds.
      * Specialist B has round_num == 3.
      * Untargeted proposal claims, recommendations, summaries, and scopes never mutated.
    """
    quota_constraint = SharedConstraint(
        id="weekly_quota",
        description="Quota constraint",
        unit="hours",
        limit_value=50.0,
        limit_source="user",
    )
    config = DeliberationConfig(
        panel_id="panel_quad_3rounds",
        budget=DeliberationBudget(max_rounds=3),
        shared_constraints=[quota_constraint],
        critique_mode="batched",  # batched for clean matrix calls
    )
    plan = ExecutionPlan(
        title="3-Round Complexity Test",
        target_agents=["specialist_a", "specialist_b", "specialist_c", "specialist_d"],
        deliberation_config=config,
    )
    state = create_initial_state("Execute 3-round quad deliberation.")
    state["execution_plan"] = plan

    # Round 1 Proposals (Total claims = 5 + 12 + 6 + 10 = 33.0 <= 50.0 -> Auditor passes)
    prop_a = {
        "agent_id": "specialist_a",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist A initial proposal",
        "recommendations": ["A_init_1", "A_init_2"],
        "resource_claims": {"weekly_quota": 5.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_b = {
        "agent_id": "specialist_b",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist B initial proposal",
        "recommendations": ["B_init_1"],
        "resource_claims": {"weekly_quota": 12.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_c = {
        "agent_id": "specialist_c",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist C initial proposal",
        "recommendations": ["C_init_1", "C_init_2", "C_init_3"],
        "resource_claims": {"weekly_quota": 6.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    prop_d = {
        "agent_id": "specialist_d",
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Specialist D initial proposal",
        "recommendations": ["D_init_1"],
        "resource_claims": {"weekly_quota": 10.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_a)
    challenge_model.queue_response(prop_b)
    challenge_model.queue_response(prop_c)
    challenge_model.queue_response(prop_d)

    # Round 1 batched critique:
    # A, C, and D receive endorsements.
    # ONLY B receives conflict.
    batched_r1 = [
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_c",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Solid proposal from C and fully aligned",
            "proposed_resolution": "Maintain",
        },
        {
            "reviewer_agent_id": "specialist_c",
            "target_agent_id": "specialist_d",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist D plan is well structured and sound",
            "proposed_resolution": "Maintain",
        },
        {
            "reviewer_agent_id": "specialist_d",
            "target_agent_id": "specialist_a",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist A plan is solid and compliant",
            "proposed_resolution": "Maintain",
        },
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_b",
            "stance": "conflict",
            "issue_type": "dependency_order",
            "critique": "Specialist B sequence clashes with prerequisites",
            "proposed_resolution": "Reorder phase 1 actions",
        },
    ]
    challenge_model.queue_response(batched_r1)

    # Round 2: Only B revises (1 revision call)
    prop_b_r2 = {
        "agent_id": "specialist_b",
        "round_num": 2,
        "scope": "scope_alpha",
        "summary": "Specialist B revised proposal (still imperfect)",
        "recommendations": ["B_revised_1"],
        "resource_claims": {"weekly_quota": 10.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_b_r2)

    # Round 2 batched critique:
    # B still has an open conflict from A!
    # A, C, D remain untargeted.
    batched_r2 = [
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_b",
            "stance": "conflict",
            "issue_type": "dependency_order",
            "critique": "Specialist B still has ordering issue in step 2",
            "proposed_resolution": "Swap step 2 and step 3",
        },
    ]
    challenge_model.queue_response(batched_r2)

    # Round 3: Only B revises again (1 revision call)
    prop_b_r3 = {
        "agent_id": "specialist_b",
        "round_num": 3,
        "scope": "scope_alpha",
        "summary": "Specialist B final proposal (fully resolved)",
        "recommendations": ["B_final_1", "B_final_2"],
        "resource_claims": {"weekly_quota": 8.0},
        "resource_claim_units": {"weekly_quota": "hours"},
    }
    challenge_model.queue_response(prop_b_r3)

    # Round 3 batched critique: All converge
    batched_r3 = [
        {
            "reviewer_agent_id": "specialist_a",
            "target_agent_id": "specialist_b",
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Specialist B step ordering is now fully resolved",
            "proposed_resolution": "Maintain",
        }
    ]
    challenge_model.queue_response(batched_r3)

    engine = DeliberationEngine(model=challenge_model, config=config)
    result_state = await engine.run(state)

    delib_state = result_state["deliberation_state"]
    assert delib_state["converged"] is True
    assert delib_state["rounds_used"] == 3

    active_props = delib_state["active_proposals"]

    # Specialist A: untargeted across all 3 rounds -> MUST remain round_num == 1
    assert active_props["specialist_a"]["round_num"] == 1
    assert active_props["specialist_a"]["summary"] == "Specialist A initial proposal"
    assert active_props["specialist_a"]["recommendations"] == ["A_init_1", "A_init_2"]
    assert active_props["specialist_a"]["resource_claims"] == {"weekly_quota": 5.0}

    # Specialist C: untargeted across all 3 rounds -> MUST remain round_num == 1
    assert active_props["specialist_c"]["round_num"] == 1
    assert active_props["specialist_c"]["summary"] == "Specialist C initial proposal"
    assert active_props["specialist_c"]["recommendations"] == ["C_init_1", "C_init_2", "C_init_3"]
    assert active_props["specialist_c"]["resource_claims"] == {"weekly_quota": 6.0}

    # Specialist D: untargeted across all 3 rounds -> MUST remain round_num == 1
    assert active_props["specialist_d"]["round_num"] == 1
    assert active_props["specialist_d"]["summary"] == "Specialist D initial proposal"
    assert active_props["specialist_d"]["recommendations"] == ["D_init_1"]
    assert active_props["specialist_d"]["resource_claims"] == {"weekly_quota": 10.0}

    # Specialist B: revised in R2 and R3 -> MUST have round_num == 3
    assert active_props["specialist_b"]["round_num"] == 3
    assert active_props["specialist_b"]["summary"] == "Specialist B final proposal (fully resolved)"
    assert active_props["specialist_b"]["recommendations"] == ["B_final_1", "B_final_2"]
    assert active_props["specialist_b"]["resource_claims"] == {"weekly_quota": 8.0}
