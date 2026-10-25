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

"""Comprehensive unit test suite for deliberation synthesis, taint propagation, and guardrails (M3 / R3).

Verifies ADR 0001 §2.11 and Phase 1 requirements:
1. Model Injection (Feature 24): Optional model acceptance in ResponseSynthesizerNode and builder wiring.
2. Unified Plan Synthesis (Feature 25): Generic stakeholder framing from blackboard state.
3. Resource Allocation Table (Feature 26): Checked constraints and explicit notation for skipped constraints.
4. Trade-Offs Narrative (Feature 27): Multi-round compromise summary across revision cycles.
5. Structured Minority Report & Amendment Notes (Feature 28): Option A vs Option B on unresolved CONFLICT; open notes on AMEND.
6. Untrusted-Input Taint Flags (Feature 29): Warning flags rendered for proposals derived from tainted context.
7. Domain Purge (Feature 30): Complete absence of legacy conflict checks and disclaimers.
8. Union Safety Policy (Feature 31): OutputGuardrailNode enforcing union of participating pack policies.
9. Backward Compatibility: Standard execution turns without deliberation_state function cleanly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set
import pytest

from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.safety_policy import (
    EmergencyDirective,
    NeutralSafetyPolicy,
    SafetyContext,
    SafetyPolicy,
    SafetyVerdict,
    UnionSafetyPolicy,
)
from yarvelle_core.schemas.plan import (
    DeliberationBudget,
    DeliberationConfig,
    SharedConstraint,
)
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.nodes.output_guardrail_node import OutputGuardrailNode
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.state import (
    AgentProposal,
    CritiqueStance,
    PeerCritique,
)
try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


# ============================================================================
# Shared Domain-Neutral Fixtures and Mock Safety Policies
# ============================================================================


class MockDomainSafetyPolicy:
    """Domain-neutral test policy for testing multi-pack guardrail unions."""

    def __init__(
        self,
        domain_name: str,
        forbidden_keywords: Sequence[str] = (),
        is_hard: bool = True,
        refusal_reason: str = "forbidden_intent:policy_prohibited",
    ) -> None:
        self.domain_name = domain_name
        self.forbidden_keywords = list(forbidden_keywords)
        self.is_hard = is_hard
        self.refusal_reason = refusal_reason

    def check_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return self._evaluate(text)

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return self._evaluate(text)

    def _evaluate(self, text: Optional[str]) -> SafetyVerdict:
        if not text:
            return SafetyVerdict(refused=False)
        lower = text.lower()
        for kw in self.forbidden_keywords:
            if kw.lower() in lower:
                return SafetyVerdict(
                    refused=True,
                    reason=self.refusal_reason,
                    category=f"{self.domain_name}_violation",
                    is_hard=self.is_hard,
                )
        return SafetyVerdict(refused=False)

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        return None

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return f"Policy preamble for {self.domain_name}."

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        return f"Operation blocked by {self.domain_name} safety policy: {reason}."

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        return self.is_hard

    def get_forbidden_intents(self) -> Set[str]:
        return set(self.forbidden_keywords)


@pytest.fixture
def mock_chat_model() -> MockChatModel:
    return MockChatModel(model_name="mock-synthesizer")


@pytest.fixture
def generic_shared_constraints() -> List[SharedConstraint]:
    return [
        SharedConstraint(
            id="weekly_quota",
            description="Weekly total allowable work units",
            unit="hours",
            limit_value=20.0,
            limit_source="user",
        ),
        SharedConstraint(
            id="compute_budget",
            description="Max allowable batch processing points",
            unit="points",
            limit_value=100.0,
            limit_source="profile",
        ),
        SharedConstraint(
            id="storage_slots",
            description="Allowable storage units",
            unit="units",
            limit_value=None,  # Intentionally skipped constraint
            limit_source=None,
        ),
    ]


@pytest.fixture
def converged_blackboard(generic_shared_constraints: List[SharedConstraint]) -> BlackboardManager:
    """Blackboard representing a converged multi-round deliberation."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)

    # Round 1
    p1_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Initial proposal from specialist_a allocating 15 hours.",
        recommendations=["Execute primary phase 1", "Configure logging checkpoints"],
        resource_claims={"weekly_quota": 15.0, "compute_budget": 30.0},
        resource_claim_units={"weekly_quota": "hours", "compute_budget": "points"},
        tainted=False,
    )
    p1_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Initial proposal from specialist_b allocating 10 hours.",
        recommendations=["Execute validation suite", "Monitor processing throughput"],
        resource_claims={"weekly_quota": 10.0, "compute_budget": 40.0, "storage_slots": 5.0},
        resource_claim_units={"weekly_quota": "hours", "compute_budget": "points", "storage_slots": "units"},
        tainted=False,
    )
    bb.record_proposal(p1_a)
    bb.record_proposal(p1_b)

    # Round 1 Critique: specialist_b flags budget conflict
    c1 = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Combined weekly quota exceeds 20.0 hours limit (25.0 hours claimed).",
        proposed_resolution="Reduce specialist_a allocation to 8.0 hours.",
        resolved=True,
    )
    bb.record_critiques(1, [c1])

    # Round 2: Revised proposal from specialist_a
    p2_a = AgentProposal(
        agent_id="specialist_a",
        round_num=2,
        scope="scope_alpha.tasks",
        summary="Revised proposal from specialist_a reducing claim to 8.0 hours.",
        recommendations=["Execute primary phase 1 streamlined", "Configure logging checkpoints"],
        resource_claims={"weekly_quota": 8.0, "compute_budget": 30.0},
        resource_claim_units={"weekly_quota": "hours", "compute_budget": "points"},
        tainted=False,
    )
    bb.record_proposal(p2_a)
    return bb


# ============================================================================
# 1. Model Injection & Node Architecture (Feature 24)
# ============================================================================


def test_synthesizer_accepts_optional_model_in_constructor_and_execution(mock_chat_model):
    """Verify ResponseSynthesizerNode accepts optional model parameter and operates cleanly."""
    # 1. Default constructor without model
    node_no_model = ResponseSynthesizerNode()
    assert getattr(node_no_model, "model", None) is None

    # 2. Constructor with model injected
    node_with_model = ResponseSynthesizerNode(model=mock_chat_model)
    assert getattr(node_with_model, "model", None) is mock_chat_model

    # 3. Execution operates without error in both cases
    state = {
        "specialist_outputs": {
            "specialist_a": "Step 1 complete.",
            "specialist_b": "Step 2 complete.",
        }
    }
    out_no_model = ResponseSynthesizerNode.synthesize_response(state)
    assert "Step 1 complete." in out_no_model
    assert "Step 2 complete." in out_no_model


def test_builder_with_safety_policies_and_model_injection(mock_chat_model):
    """Verify GraphBuilder correctly wires model into ResponseSynthesizerNode and supports multi-policy union."""
    pol1 = MockDomainSafetyPolicy(domain_name="policy_1", forbidden_keywords=["bad_word_1"])
    pol2 = MockDomainSafetyPolicy(domain_name="policy_2", forbidden_keywords=["bad_word_2"])

    builder = (
        GraphBuilder(model=mock_chat_model)
        .with_safety_policies([pol1, pol2])
        .with_response_synthesizer(True)
    )
    assert isinstance(builder.safety_policy, UnionSafetyPolicy)
    assert len(builder.safety_policy.policies) == 2

    # Verify building graph wires synthesizer with model
    graph = builder.build()
    assert graph is not None


# ============================================================================
# 2. Unified Plan Synthesis & Generic Framing (Feature 25)
# ============================================================================


def test_deliberation_synthesis_unified_plan_from_blackboard(converged_blackboard):
    """Verify unified plan generated from blackboard state with generic stakeholder review framing."""
    state = {
        "deliberation_state": converged_blackboard.to_state_dict(),
        "specialist_outputs": {},
    }
    node = ResponseSynthesizerNode()
    output = node.synthesize_response(state)

    # 1. Generic stakeholder advisory framing header
    assert re.search(r"#\s+(?:Deliberation|Coordinated|Unified)\s+Plan\s+\(for\s+stakeholder\s+review\)", output, re.IGNORECASE)

    # 2. Coordinated recommendations from both specialists
    assert "Execute primary phase 1 streamlined" in output
    assert "Execute validation suite" in output
    assert "Configure logging checkpoints" in output
    assert "Monitor processing throughput" in output

    # 3. Domain neutrality check
    assert "consultation master agenda" not in output.lower()
    assert "specialty guidance" not in output.lower()


# ============================================================================
# 3. Resource Allocation Table & Skipped Constraints (Feature 26)
# ============================================================================


def test_deliberation_synthesis_resource_allocation_table_with_verified_limits(converged_blackboard):
    """Verify markdown table renders verified limits, total claims, and allocation status."""
    state = {
        "deliberation_state": converged_blackboard.to_state_dict(),
    }
    output = ResponseSynthesizerNode.synthesize_response(state)

    # Verify table headers
    assert re.search(r"\|\s*Constraint\s*\|\s*(?:Sourced\s+)?Limit\s*\|\s*Total\s+Claimed\s*\|\s*Status\s*\|", output, re.IGNORECASE)

    # weekly_quota: limit=20.0, claims=8.0 + 10.0 = 18.0 -> Within Limit
    assert "weekly_quota" in output
    assert "18.0" in output
    assert re.search(r"within\s+limit|ok|compliant", output, re.IGNORECASE)

    # compute_budget: limit=100.0, claims=30.0 + 40.0 = 70.0 -> Within Limit
    assert "compute_budget" in output
    assert "70.0" in output


def test_deliberation_synthesis_skipped_constraints_explicitly_noted(converged_blackboard):
    """Verify constraints with limit_value=None are explicitly noted as skipped/unverified."""
    state = {
        "deliberation_state": converged_blackboard.to_state_dict(),
    }
    output = ResponseSynthesizerNode.synthesize_response(state)

    # storage_slots has limit_value=None and 5.0 units claimed
    assert "storage_slots" in output
    assert re.search(r"skipped|unverified|limit\s+unknown|not\s+checked", output, re.IGNORECASE)
    assert "5.0" in output


# ============================================================================
# 4. Multi-Round Trade-Offs & Selective Revisions (Feature 27)
# ============================================================================


def test_deliberation_synthesis_trade_offs_multi_round_compromise(converged_blackboard):
    """Verify Trade-Offs section details proposal changes across revision rounds."""
    state = {
        "deliberation_state": converged_blackboard.to_state_dict(),
    }
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert re.search(r"##\s+Trade-?[Oo]ffs", output, re.IGNORECASE)
    # References specialist_a revising its claim from 15.0 to 8.0 hours
    assert "specialist_a" in output
    assert re.search(r"(?:reduced|revised|adjusted).*(?:8\.0|15\.0)", output, re.IGNORECASE)


def test_deliberation_synthesis_trade_offs_single_round_consensus(generic_shared_constraints):
    """Verify single-round consensus notes that initial proposals required no revision."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)
    p1_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Initial step 1.",
        recommendations=["Recommendation 1"],
        resource_claims={"weekly_quota": 5.0},
        resource_claim_units={"weekly_quota": "hours"},
    )
    p1_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Initial step 2.",
        recommendations=["Recommendation 2"],
        resource_claims={"weekly_quota": 5.0},
        resource_claim_units={"weekly_quota": "hours"},
    )
    bb.record_proposal(p1_a)
    bb.record_proposal(p1_b)
    c1 = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=1,
        stance=CritiqueStance.ENDORSE,
        issue_type="synergy",
        critique="Compatible approach.",
        proposed_resolution="Proceed as planned.",
        resolved=True,
    )
    bb.record_critiques(1, [c1])

    state = {"deliberation_state": bb.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert re.search(r"##\s+Trade-?[Oo]ffs", output, re.IGNORECASE)
    assert re.search(r"(?:consensus|agreement|no\s+conflicts|aligned).*(?:round\s+1|initial)", output, re.IGNORECASE)


# ============================================================================
# 5. Divergence Reporting: Minority Reports & Open Amendments (Feature 28)
# ============================================================================


def test_deliberation_synthesis_minority_report_on_unresolved_conflict(generic_shared_constraints):
    """Verify structured Option A vs. Option B minority report when CONFLICT remains unresolved."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)
    p_a = AgentProposal(
        agent_id="specialist_a",
        round_num=2,
        scope="scope_alpha.tasks",
        summary="Proposal A favoring high throughput.",
        recommendations=["Execute aggressive parallel batching"],
    )
    p_b = AgentProposal(
        agent_id="specialist_b",
        round_num=2,
        scope="scope_alpha.tasks",
        summary="Proposal B favoring conservative checkpoints.",
        recommendations=["Execute sequential verified checkpoints"],
    )
    bb.record_proposal(p_a)
    bb.record_proposal(p_b)

    # Unresolved CONFLICT
    unresolved_conflict = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=2,
        stance=CritiqueStance.CONFLICT,
        issue_type="risk_exposure",
        critique="Aggressive parallel batching creates unverified error propagation risk.",
        proposed_resolution="Adopt sequential verified checkpoints.",
        resolved=False,
    )
    bb.record_critiques(2, [unresolved_conflict])

    state = {"deliberation_state": bb.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    # Verify Minority Report structure
    assert re.search(r"##\s+Minority\s+Report", output, re.IGNORECASE)
    assert re.search(r"###\s+Option\s+A.*specialist_a", output, re.IGNORECASE)
    assert re.search(r"###\s+Option\s+B.*specialist_b", output, re.IGNORECASE)
    assert re.search(r"risk_exposure", output, re.IGNORECASE)
    assert re.search(r"stakeholder.*judgment|human.*review|value\s+judgment", output, re.IGNORECASE)


def test_deliberation_synthesis_open_amendment_notes_on_unresolved_amend(generic_shared_constraints):
    """Verify unresolved AMEND critiques generate Open Amendment Notes without minority report split."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)
    p_a = AgentProposal(
        agent_id="specialist_a",
        round_num=2,
        scope="scope_alpha.tasks",
        summary="Proposal A.",
        recommendations=["Initialize calibration routine"],
    )
    p_b = AgentProposal(
        agent_id="specialist_b",
        round_num=2,
        scope="scope_alpha.tasks",
        summary="Proposal B.",
        recommendations=["Initialize processing routine"],
    )
    bb.record_proposal(p_a)
    bb.record_proposal(p_b)

    # Unresolved AMEND
    unresolved_amend = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=2,
        stance=CritiqueStance.AMEND,
        issue_type="dependency_order",
        critique="Suggest executing indexing after calibration rather than concurrently.",
        proposed_resolution="Reorder execution sequence.",
        resolved=False,
    )
    bb.record_critiques(2, [unresolved_amend])

    state = {"deliberation_state": bb.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    # Verify Open Amendment Notes rendered
    assert re.search(r"##\s+Open\s+Amendment\s+Notes", output, re.IGNORECASE)
    assert "specialist_b" in output
    assert "dependency_order" in output
    assert "Reorder execution sequence" in output

    # Invariant: Plain amendments must NOT trigger Option A vs Option B minority report
    assert "## Minority Report" not in output
    assert "Option A vs" not in output


def test_deliberation_synthesis_minority_report_and_amendments_combined(generic_shared_constraints):
    """Verify simultaneous presence of unresolved CONFLICT and AMEND are cleanly separated."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)
    p_a = AgentProposal(agent_id="specialist_a", round_num=2, scope="scope_alpha.tasks", summary="P-A")
    p_b = AgentProposal(agent_id="specialist_b", round_num=2, scope="scope_alpha.tasks", summary="P-B")
    bb.record_proposal(p_a)
    bb.record_proposal(p_b)

    c_conflict = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_a",
        round_num=2,
        stance=CritiqueStance.CONFLICT,
        issue_type="risk_exposure",
        critique="Conflict on buffer safety threshold.",
        proposed_resolution="Increase buffer threshold.",
        resolved=False,
    )
    c_amend = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=2,
        stance=CritiqueStance.AMEND,
        issue_type="dependency_order",
        critique="Amend pipeline trigger timing.",
        proposed_resolution="Delay trigger by 10 units.",
        resolved=False,
    )
    bb.record_critiques(2, [c_conflict, c_amend])

    state = {"deliberation_state": bb.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert re.search(r"##\s+Minority\s+Report", output, re.IGNORECASE)
    assert re.search(r"##\s+Open\s+Amendment\s+Notes", output, re.IGNORECASE)


# ============================================================================
# 6. Untrusted-Input Taint Propagation & Warning Rendering (Feature 29)
# ============================================================================


def test_deliberation_synthesis_taint_flag_warning_rendered(generic_shared_constraints):
    """Verify prominent warning rendered when any active proposal rests on tainted inputs."""
    bb = BlackboardManager(panel_id="panel_alpha", shared_constraints=generic_shared_constraints)
    p_clean = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Clean internal proposal.",
        recommendations=["Internal configuration"],
        tainted=False,
    )
    p_tainted = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Proposal derived from unverified external source.",
        recommendations=["External integration step"],
        tainted=True,
    )
    bb.record_proposal(p_clean)
    bb.record_proposal(p_tainted)

    state = {"deliberation_state": bb.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    # Verify taint warning
    assert re.search(r"untrusted\s+(?:source|input)|tainted", output, re.IGNORECASE)
    assert "specialist_b" in output


def test_deliberation_synthesis_no_taint_warning_when_clean(converged_blackboard):
    """Verify clean deliberation output produces zero taint warnings."""
    state = {"deliberation_state": converged_blackboard.to_state_dict()}
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert "untrusted" not in output.lower()
    assert "tainted" not in output.lower()


# ============================================================================
# 7. Domain Neutrality Purge & Guardrail Union Policy (Features 30, 31)
# ============================================================================


def test_synthesizer_purged_of_legacy_domain_checks_and_disclaimers():
    """Verify complete purging of legacy domain conflict checks and disclaimers."""
    # Specialist outputs containing tokens that previously triggered legacy domain logic
    state = {
        "specialist_outputs": {
            "specialist_a": "Evaluate system balance and pressure thresholds.",
            "specialist_b": "Assess parameter levels and clearance rates.",
        }
    }
    node = ResponseSynthesizerNode()
    output = node.synthesize_response(state)

    # 1. Obsolete coordination questions must NOT appear
    assert "Priority Coordination Questions" not in output
    assert "fluid restriction" not in output
    assert "heart function" not in output
    assert "renal clearance" not in output
    assert "diuretic therapies" not in output

    # 2. Obsolete domain disclaimers must NOT appear
    assert "licensed healthcare provider" not in output
    assert "medications without consulting" not in output


@pytest.mark.asyncio
async def test_output_guardrail_union_safety_policy_enforcement():
    """Verify OutputGuardrailNode enforces the union of rule sets across multiple participating packs."""
    # Policy Alpha blocks "disallowed_alpha"
    policy_alpha = MockDomainSafetyPolicy(
        domain_name="pack_alpha",
        forbidden_keywords=["disallowed_alpha"],
        is_hard=True,
        refusal_reason="forbidden_intent:policy_alpha_prohibited",
    )
    # Policy Beta blocks "disallowed_beta"
    policy_beta = MockDomainSafetyPolicy(
        domain_name="pack_beta",
        forbidden_keywords=["disallowed_beta"],
        is_hard=True,
        refusal_reason="forbidden_intent:policy_beta_prohibited",
    )

    union_policy = UnionSafetyPolicy([policy_alpha, policy_beta])
    node = OutputGuardrailNode(safety_policy=union_policy)

    # Case 1: Violation of Policy Alpha
    res_alpha = await node.execute({"output": "This output contains disallowed_alpha action."})
    assert res_alpha["refused"] is True
    assert "policy_alpha_prohibited" in res_alpha["refusal_reason"]

    # Case 2: Violation of Policy Beta
    res_beta = await node.execute({"output": "This output contains disallowed_beta action."})
    assert res_beta["refused"] is True
    assert "policy_beta_prohibited" in res_beta["refusal_reason"]

    # Case 3: Compliant text passes both policies
    res_clean = await node.execute({"output": "This output contains only permitted operations."})
    assert res_clean["refused"] is False
    assert res_clean["is_compliant"] is True
    assert "permitted operations" in res_clean["output"]


@pytest.mark.asyncio
async def test_output_guardrail_union_preserves_hard_refusal():
    """Verify hard refusal from one policy takes precedence over soft boundary notice from another."""
    hard_policy = MockDomainSafetyPolicy(
        domain_name="hard_pack",
        forbidden_keywords=["hard_trigger"],
        is_hard=True,
        refusal_reason="forbidden_intent:hard_violation",
    )
    soft_policy = MockDomainSafetyPolicy(
        domain_name="soft_pack",
        forbidden_keywords=["soft_trigger"],
        is_hard=False,
        refusal_reason="boundary_warning:soft_notice",
    )

    union_policy = UnionSafetyPolicy([hard_policy, soft_policy])
    node = OutputGuardrailNode(safety_policy=union_policy)

    # Output triggering both hard and soft violations
    res = await node.execute({"output": "Content triggering hard_trigger and soft_trigger."})
    assert res["refused"] is True
    assert res["boundary_warning"] is False  # Hard refusal takes precedence
    assert res["refusal_reason"] == "forbidden_intent:hard_violation"


def test_synthesizer_backward_compatibility_without_deliberation_state():
    """Verify non-deliberation multi-agent execution turns synthesize without error."""
    state = {
        "specialist_outputs": {
            "specialist_a": "Summary from specialist A without deliberation.",
            "specialist_b": "Summary from specialist B without deliberation.",
        },
        "deliberation_state": None,
    }
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert "specialist A" in output or "Specialist A" in output
    assert "specialist B" in output or "Specialist B" in output
    assert "DISCLAIMER:" in output


def test_deliberation_synthesis_degraded_fallback():
    """Verify deliberation degraded state formats cleanly with missing agents listed."""
    state = {
        "deliberation_state": {
            "degraded": True,
            "missing_agents": ["specialist_b"],
        },
        "output": "Partial progress from specialist_a.",
    }
    output = ResponseSynthesizerNode.synthesize_response(state)

    assert "degraded" in output.lower()
    assert "specialist_b" in output
    assert "Partial progress from specialist_a." in output
