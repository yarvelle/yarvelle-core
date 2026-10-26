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

"""Empirical adversarial stress test suite for deliberation synthesis and guardrails (M3 / R3).

Adversarially challenges ResponseSynthesizerNode and UnionSafetyPolicy under:
1. Large constraint sets (50+ constraints, empty constraints, floating point precision boundaries).
2. Multi-round trade-offs tracking across 10 rounds of proposal revisions.
3. Multiple conflicting agents with overlapping conflicts, amends, and missing target agent fallbacks.
4. Taint flag propagation with mixed tainted and untainted agents and run-level taint flags.
5. Degraded single-agent fallback formatting with missing agent variations.
6. Union safety policy fail-closed and hard refusal precedence across multi-policy aggregations.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence
import pytest

from yarvelle_core.engine.safety_policy import (
    EmergencyDirective,
    SafetyContext,
    SafetyPolicy,
    SafetyVerdict,
    UnionSafetyPolicy,
)
from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.nodes.output_guardrail_node import OutputGuardrailNode
from yarvelle_core.workflows.nodes.response_synthesizer_node import (
    CANONICAL_DISCLAIMER,
    ResponseSynthesizerNode,
)
from yarvelle_core.workflows.state import (
    AgentProposal,
    CritiqueStance,
    PeerCritique,
)


class MockAdversarialSafetyPolicy:
    """Domain-neutral adversarial safety policy double."""

    def __init__(
        self,
        domain_name: str,
        forbidden_keywords: Sequence[str] = (),
        is_hard: bool = True,
        refusal_reason: str = "forbidden_intent:policy_prohibited",
        emergency_keyword: Optional[str] = None,
    ) -> None:
        self.domain_name = domain_name
        self.forbidden_keywords = list(forbidden_keywords)
        self.is_hard = is_hard
        self.refusal_reason = refusal_reason
        self.emergency_keyword = emergency_keyword

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
        if not text:
            return None
        if self.emergency_keyword and self.emergency_keyword.lower() in text.lower():
            return EmergencyDirective(
                detected=True,
                category="system_critical_failure",
                trigger_phrase=self.emergency_keyword,
                referral_message=f"Critical emergency alert raised by {self.domain_name}",
            )
        return None

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return f"Safety preamble from {self.domain_name}"

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        return f"Refusal template from {self.domain_name} for {reason}"

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        return self.is_hard and (reason == self.refusal_reason)


# ============================================================================
# 1. Large Constraint Sets & Boundary Float Precision Stress Tests
# ============================================================================


def test_stress_large_constraint_set_50_plus():
    """Stress-tests table generation and arithmetic summation with 60 constraints."""
    node = ResponseSynthesizerNode()

    num_constraints = 60
    constraints: List[SharedConstraint] = []
    claims_a: Dict[str, float] = {}
    claims_b: Dict[str, float] = {}

    for i in range(num_constraints):
        cid = f"constraint_{i:02d}"
        if i % 5 == 0:
            # Skipped constraint with None limit
            c = SharedConstraint(id=cid, description=f"Resource {i}", unit="units")
        elif i % 5 == 1:
            # Overbudget constraint
            c = SharedConstraint(id=cid, description=f"Resource {i}", unit="hours", limit_value=10.0, limit_source="user")
            claims_a[cid] = 7.0
            claims_b[cid] = 5.0
        elif i % 5 == 2:
            # Exactly at limit constraint
            c = SharedConstraint(id=cid, description=f"Resource {i}", unit="points", limit_value=20.0, limit_source="profile")
            claims_a[cid] = 12.0
            claims_b[cid] = 8.0
        elif i % 5 == 3:
            # Zero limit constraint
            c = SharedConstraint(id=cid, description=f"Resource {i}", unit="items", limit_value=0.0, limit_source="user")
            claims_a[cid] = 0.0
            claims_b[cid] = 0.0
        else:
            # Normal well-within limit
            c = SharedConstraint(id=cid, description=f"Resource {i}", unit="count", limit_value=100.0, limit_source="user")
            claims_a[cid] = 15.0
            claims_b[cid] = 10.0
        constraints.append(c)

    prop_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal A for large constraint set.",
        recommendations=["Action A1", "Action A2"],
        resource_claims=claims_a,
    )
    prop_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal B for large constraint set.",
        recommendations=["Action B1"],
        resource_claims=claims_b,
    )

    delib_state = {
        "panel_id": "large_panel_01",
        "shared_constraints": [c.model_dump() for c in constraints],
        "proposals": {1: {"specialist_a": prop_a.model_dump(), "specialist_b": prop_b.model_dump()}},
        "active_proposals": {"specialist_a": prop_a.model_dump(), "specialist_b": prop_b.model_dump()},
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    assert "# Deliberation Plan (for stakeholder review)" in output
    assert "## Resource Allocation & Shared Constraints" in output

    # Check table structure has all 60 constraint rows plus headers
    table_lines = [line for line in output.splitlines() if line.startswith("| constraint_")]
    assert len(table_lines) == 60

    # Verify skipped constraint formatting
    assert "| constraint_00 | None (Skipped) | 0.0 units | Limit Unknown (Skipped) |" in output
    # Verify overbudget formatting (7.0 + 5.0 = 12.0 vs 10.0 limit)
    assert "| constraint_01 | 10.0 hours (user) | 12.0 hours | Overbudget (+2.0) |" in output
    # Verify exact limit formatting (12.0 + 8.0 = 20.0 vs 20.0 limit)
    assert "| constraint_02 | 20.0 points (profile) | 20.0 points | Within limit |" in output
    # Verify zero limit formatting
    assert "| constraint_03 | 0.0 items (user) | 0.0 items | Within limit |" in output
    # Verify skipped footnote
    assert "*Note: Constraints with unknown limits were not checked against a budget boundary.*" in output


def test_stress_empty_and_none_shared_constraints():
    """Verifies synthesis behavior when shared_constraints is empty list or empty panel."""
    node = ResponseSynthesizerNode()

    prop_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Consensus plan with no constraints.",
        recommendations=["Execute primary flow"],
    )
    prop_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha",
        summary="Peer consensus plan.",
        recommendations=["Execute secondary flow"],
    )

    delib_state = {
        "panel_id": "unconstrained_panel",
        "shared_constraints": [],
        "proposals": {1: {"specialist_a": prop_a.model_dump(), "specialist_b": prop_b.model_dump()}},
        "active_proposals": {"specialist_a": prop_a.model_dump(), "specialist_b": prop_b.model_dump()},
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    assert "## Resource Allocation & Shared Constraints" in output
    assert "*No shared resource constraints declared for this panel.*" in output
    assert "| Constraint |" not in output
    assert "*Note: Constraints with unknown limits were not checked" not in output


def test_stress_floating_point_precision_boundaries():
    """Adversarially tests floating point threshold boundaries (1e-9 tolerance)."""
    node = ResponseSynthesizerNode()

    # Constraints for boundary testing
    c_exact = SharedConstraint(id="c_exact", description="Exact match test", unit="units", limit_value=20.0, limit_source="user")
    c_under = SharedConstraint(id="c_under", description="Under limit test", unit="units", limit_value=20.0, limit_source="user")
    c_at_threshold = SharedConstraint(id="c_at_threshold", description="Threshold delta test", unit="units", limit_value=20.0, limit_source="user")
    c_over_threshold = SharedConstraint(id="c_over_threshold", description="Over threshold test", unit="units", limit_value=20.0, limit_source="user")
    c_accumulator = SharedConstraint(id="c_accumulator", description="Accumulator rounding test", unit="units", limit_value=0.3, limit_source="user")

    # c_exact: claimed = 20.0 exactly
    # c_under: claimed = 19.999999999999
    # c_at_threshold: claimed = 20.0 + 1e-9 (delta == 1e-9, not > 1e-9) -> Within limit
    # c_over_threshold: claimed = 20.0 + 2e-9 (delta > 1e-9) -> Overbudget
    # c_accumulator: 0.1 + 0.1 + 0.1 in float is 0.30000000000000004 -> delta <= 1e-9 -> Within limit

    prop_a = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Float boundary proposal A",
        resource_claims={
            "c_exact": 10.0,
            "c_under": 9.999999999999,
            "c_at_threshold": 10.0,
            "c_over_threshold": 10.0,
            "c_accumulator": 0.1,
        },
    )
    prop_b = AgentProposal(
        agent_id="specialist_b",
        round_num=1,
        scope="scope_alpha",
        summary="Float boundary proposal B",
        resource_claims={
            "c_exact": 10.0,
            "c_under": 10.0,
            "c_at_threshold": 10.0 + 1e-9,
            "c_over_threshold": 10.0 + 2e-9,
            "c_accumulator": 0.1,
        },
    )
    prop_c = AgentProposal(
        agent_id="specialist_c",
        round_num=1,
        scope="scope_alpha",
        summary="Float boundary proposal C",
        resource_claims={
            "c_accumulator": 0.1,
        },
    )

    delib_state = {
        "panel_id": "float_panel",
        "shared_constraints": [
            c_exact.model_dump(),
            c_under.model_dump(),
            c_at_threshold.model_dump(),
            c_over_threshold.model_dump(),
            c_accumulator.model_dump(),
        ],
        "proposals": {
            1: {
                "specialist_a": prop_a.model_dump(),
                "specialist_b": prop_b.model_dump(),
                "specialist_c": prop_c.model_dump(),
            }
        },
        "active_proposals": {
            "specialist_a": prop_a.model_dump(),
            "specialist_b": prop_b.model_dump(),
            "specialist_c": prop_c.model_dump(),
        },
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    # Verify exact equality is within limit
    assert "| c_exact | 20.0 units (user) | 20.0 units | Within limit |" in output
    # Verify epsilon under limit is within limit
    assert "| c_under | 20.0 units (user) | 20.0 units | Within limit |" in output
    # Verify 20.000000001 (diff 1.00000008e-9 > 1e-9) evaluates to Overbudget (+0.0)
    assert "| c_at_threshold | 20.0 units (user) | 20.0 units | Overbudget (+0.0) |" in output
    # Verify delta > 1e-9 triggers overbudget
    assert "| c_over_threshold | 20.0 units (user) | 20.0 units | Overbudget (+0.0) |" in output
    # Verify float accumulator (0.1 + 0.1 + 0.1 = 0.30000000000000004) is within limit (no false positive)
    assert "| c_accumulator | 0.3 units (user) | 0.3 units | Within limit |" in output


def test_stress_skipped_constraints_explicit_and_implicit():
    """Tests constraints skipped via None limit_value and constraints flagged in skipped_constraints list."""
    node = ResponseSynthesizerNode()

    c_none = SharedConstraint(id="c_none", description="Constraint with no limit", unit="hours")
    c_flagged = SharedConstraint(id="c_flagged", description="Flagged skipped constraint", unit="points", limit_value=50.0, limit_source="user")
    c_normal = SharedConstraint(id="c_normal", description="Normal verified constraint", unit="units", limit_value=100.0, limit_source="user")

    prop = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal with skipped constraints",
        resource_claims={"c_none": 15.0, "c_flagged": 30.0, "c_normal": 25.0},
    )

    delib_state = {
        "panel_id": "skip_panel",
        "shared_constraints": [c_none.model_dump(), c_flagged.model_dump(), c_normal.model_dump()],
        "proposals": {1: {"specialist_a": prop.model_dump()}},
        "active_proposals": {"specialist_a": prop.model_dump()},
        "critiques": {},
        "rounds_used": 1,
        "skipped_constraints": ["c_flagged"],  # Explicitly flagged as skipped by auditor
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    assert "| c_none | None (Skipped) | 15.0 hours | Limit Unknown (Skipped) |" in output
    assert "| c_flagged | None (Skipped) | 30.0 points | Limit Unknown (Skipped) |" in output
    assert "| c_normal | 100.0 units (user) | 25.0 units | Within limit |" in output
    assert "*Note: Constraints with unknown limits were not checked against a budget boundary.*" in output


# ============================================================================
# 2. Multi-Round Trade-Offs Tracking Across 10 Rounds Stress Tests
# ============================================================================


def test_stress_multi_round_trade_offs_across_10_rounds():
    """Stress-tests progressive multi-round trade-offs across 10 rounds with 4 agents."""
    node = ResponseSynthesizerNode()

    c_alpha = SharedConstraint(id="quota_alpha", description="Alpha quota", unit="hours", limit_value=40.0, limit_source="user")
    c_beta = SharedConstraint(id="quota_beta", description="Beta quota", unit="points", limit_value=50.0, limit_source="user")

    # Round 1 baseline proposals
    r1_props = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=1,
            scope="scope_alpha",
            summary="Initial plan from Agent A",
            resource_claims={"quota_alpha": 30.0, "quota_beta": 20.0},
        ),
        "agent_b": AgentProposal(
            agent_id="agent_b",
            round_num=1,
            scope="scope_alpha",
            summary="Initial plan from Agent B",
            resource_claims={"quota_alpha": 25.0, "quota_beta": 25.0},
        ),
        "agent_c": AgentProposal(
            agent_id="agent_c",
            round_num=1,
            scope="scope_alpha",
            summary="Initial plan from Agent C",
            resource_claims={"quota_alpha": 10.0, "quota_beta": 15.0},
        ),
        "agent_d": AgentProposal(
            agent_id="agent_d",
            round_num=1,
            scope="scope_alpha",
            summary="Initial plan from Agent D",
            resource_claims={"quota_beta": 10.0},
        ),
    }

    proposals_history: Dict[int, Dict[str, Any]] = {
        1: {aid: p.model_dump() for aid, p in r1_props.items()}
    }

    # Simulate 9 subsequent revision rounds (Rounds 2 to 10)
    proposals_history[2] = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=2,
            scope="scope_alpha",
            summary="Agent A reduced quota alpha",
            resource_claims={"quota_alpha": 20.0, "quota_beta": 20.0},
        ).model_dump()
    }
    proposals_history[3] = {
        "agent_b": AgentProposal(
            agent_id="agent_b",
            round_num=3,
            scope="scope_alpha",
            summary="Agent B reduced quota alpha",
            resource_claims={"quota_alpha": 15.0, "quota_beta": 25.0},
        ).model_dump()
    }
    proposals_history[4] = {
        "agent_c": AgentProposal(
            agent_id="agent_c",
            round_num=4,
            scope="scope_alpha",
            summary="Agent C dropped quota alpha claim",
            resource_claims={"quota_beta": 15.0},
        ).model_dump()
    }
    proposals_history[5] = {
        "agent_d": AgentProposal(
            agent_id="agent_d",
            round_num=5,
            scope="scope_alpha",
            summary="Agent D revised recommendation sequencing based on peer review",
            resource_claims={"quota_beta": 10.0},
        ).model_dump()
    }
    proposals_history[6] = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=6,
            scope="scope_alpha",
            summary="Agent A adjusted quota beta",
            resource_claims={"quota_alpha": 20.0, "quota_beta": 15.0},
        ).model_dump()
    }
    proposals_history[7] = {
        "agent_b": AgentProposal(
            agent_id="agent_b",
            round_num=7,
            scope="scope_alpha",
            summary="Agent B adjusted quota beta",
            resource_claims={"quota_alpha": 15.0, "quota_beta": 20.0},
        ).model_dump()
    }
    proposals_history[8] = {
        "agent_c": AgentProposal(
            agent_id="agent_c",
            round_num=8,
            scope="scope_alpha",
            summary="Agent C adjusted quota beta",
            resource_claims={"quota_beta": 10.0},
        ).model_dump()
    }
    proposals_history[9] = {
        "agent_d": AgentProposal(
            agent_id="agent_d",
            round_num=9,
            scope="scope_alpha",
            summary="Agent D adjusted quota beta",
            resource_claims={"quota_beta": 12.0},
        ).model_dump()
    }
    proposals_history[10] = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=10,
            scope="scope_alpha",
            summary="Agent A final optimization",
            resource_claims={"quota_alpha": 18.0, "quota_beta": 14.0},
        ).model_dump()
    }

    active_props = {
        "agent_a": proposals_history[10]["agent_a"],
        "agent_b": proposals_history[7]["agent_b"],
        "agent_c": proposals_history[8]["agent_c"],
        "agent_d": proposals_history[9]["agent_d"],
    }

    delib_state = {
        "panel_id": "ten_round_panel",
        "shared_constraints": [c_alpha.model_dump(), c_beta.model_dump()],
        "proposals": proposals_history,
        "active_proposals": active_props,
        "critiques": {},
        "rounds_used": 10,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    assert "## Trade-Offs & Multi-Round Revisions" in output
    assert "Across 10 deliberation rounds, panel members negotiated the following trade-offs:" in output

    assert "- **agent_a** revised proposal in Round 2: reduced `quota_alpha` allocation from 30.0 to 20.0." in output
    assert "- **agent_b** revised proposal in Round 3: reduced `quota_alpha` allocation from 25.0 to 15.0." in output
    assert "- **agent_c** revised proposal in Round 4: removed claim on `quota_alpha` (10.0)." in output
    assert "- **agent_d** revised proposal in Round 5: revised recommendations to address peer critique." in output
    assert "- **agent_a** revised proposal in Round 6: reduced `quota_alpha` allocation from 30.0 to 20.0, reduced `quota_beta` allocation from 20.0 to 15.0." in output
    assert "- **agent_b** revised proposal in Round 7: reduced `quota_alpha` allocation from 25.0 to 15.0, reduced `quota_beta` allocation from 25.0 to 20.0." in output
    assert "- **agent_c** revised proposal in Round 8: reduced `quota_beta` allocation from 15.0 to 10.0, removed claim on `quota_alpha` (10.0)." in output
    assert "- **agent_d** revised proposal in Round 9: adjusted `quota_beta` allocation from 10.0 to 12.0." in output
    assert "- **agent_a** revised proposal in Round 10: reduced `quota_alpha` allocation from 30.0 to 18.0, reduced `quota_beta` allocation from 20.0 to 14.0." in output


# ============================================================================
# 3. Multiple Conflicting Agents & Overlapping Conflicts/Amends Stress Tests
# ============================================================================


def test_stress_multiple_conflicting_agents_and_amends_graph():
    """Adversarially stress-tests a complex 5-agent graph with multiple overlapping CONFLICT and AMEND critiques."""
    node = ResponseSynthesizerNode()

    proposals = {
        f"specialist_{i}": AgentProposal(
            agent_id=f"specialist_{i}",
            round_num=2,
            scope="scope_alpha",
            summary=f"Specialist {i} strategic blueprint.",
            recommendations=[f"Directive {i}.1", f"Directive {i}.2"],
        ).model_dump()
        for i in range(1, 6)
    }

    critiques = [
        PeerCritique(
            reviewer_agent_id="specialist_2",
            target_agent_id="specialist_1",
            round_num=2,
            stance=CritiqueStance.CONFLICT,
            issue_type="dependency_order",
            critique="Execution sequence produces circular dependency with specialist 2 tasks.",
            proposed_resolution="Defer step 1 until step 2 verification completes.",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_3",
            target_agent_id="specialist_2",
            round_num=2,
            stance=CritiqueStance.CONFLICT,
            issue_type="risk_exposure",
            critique="Threshold parameters exceed allowable risk budget for standard execution.",
            proposed_resolution="Constrain risk parameter to 0.05 threshold.",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_1",
            target_agent_id="specialist_3",
            round_num=2,
            stance=CritiqueStance.CONFLICT,
            issue_type="resource_overbudget",
            critique="Allocation requests exceed available quota for processing window.",
            proposed_resolution="Reduce processing allocation by 20%.",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_4",
            target_agent_id="specialist_1",
            round_num=2,
            stance=CritiqueStance.AMEND,
            issue_type="synergy",
            critique="Incorporate contingency buffer for unforeseen processing latency.",
            proposed_resolution="Append 10-minute contingency buffer to timeline.",
            resolved=False,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_5",
            target_agent_id="specialist_2",
            round_num=2,
            stance=CritiqueStance.AMEND,
            issue_type="dependency_order",
            critique="Synchronize check-ins at milestone boundaries.",
            proposed_resolution="Align reporting cadence to weekly intervals.",
            resolved=False,
        ),
        # Resolved items that MUST NOT appear as unresolved
        PeerCritique(
            reviewer_agent_id="specialist_4",
            target_agent_id="specialist_3",
            round_num=2,
            stance=CritiqueStance.CONFLICT,
            issue_type="contraindication",
            critique="Resolved conflict item.",
            proposed_resolution="Resolved resolution.",
            resolved=True,
        ),
        PeerCritique(
            reviewer_agent_id="specialist_5",
            target_agent_id="specialist_4",
            round_num=2,
            stance=CritiqueStance.AMEND,
            issue_type="synergy",
            critique="Resolved amend item.",
            proposed_resolution="Resolved amend resolution.",
            resolved=True,
        ),
    ]

    delib_state = {
        "panel_id": "conflict_panel",
        "shared_constraints": [],
        "proposals": {2: proposals},
        "active_proposals": proposals,
        "critiques": {2: [c.model_dump() for c in critiques]},
        "rounds_used": 2,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    # Verify Minority Report
    assert "## Minority Report: Unresolved Conflicts" in output
    assert "The panel did not reach consensus on the following items. Options are presented below for stakeholder review and value judgment:" in output

    # Check Conflict 1 (specialist_1 vs specialist_2)
    assert "### Conflict: dependency_order (specialist_1 vs specialist_2)" in output
    assert "### Option A (specialist_1 Position)" in output
    assert "- **Position**: Specialist 1 strategic blueprint." in output
    assert "  - Directive 1.1" in output
    assert "### Option B (specialist_2 Position)" in output
    assert "- **Objection**: Execution sequence produces circular dependency with specialist 2 tasks." in output
    assert "- **Proposed Resolution**: Defer step 1 until step 2 verification completes." in output

    # Check Conflict 2 (specialist_2 vs specialist_3)
    assert "### Conflict: risk_exposure (specialist_2 vs specialist_3)" in output
    assert "### Option A (specialist_2 Position)" in output
    assert "### Option B (specialist_3 Position)" in output
    assert "- **Objection**: Threshold parameters exceed allowable risk budget for standard execution." in output

    # Check Conflict 3 (specialist_3 vs specialist_1)
    assert "### Conflict: resource_overbudget (specialist_3 vs specialist_1)" in output

    # Verify Open Amendments
    assert "## Open Amendment Notes" in output
    assert "- **`specialist_4` -> `specialist_1`** (synergy): Incorporate contingency buffer for unforeseen processing latency. (Proposed: Append 10-minute contingency buffer to timeline.)" in output
    assert "- **`specialist_5` -> `specialist_2`** (dependency_order): Synchronize check-ins at milestone boundaries. (Proposed: Align reporting cadence to weekly intervals.)" in output

    # Verify resolved items are completely excluded
    assert "Resolved conflict item" not in output
    assert "Resolved amend item" not in output


def test_stress_conflict_with_missing_target_proposal():
    """Verifies graceful handling when target_agent_id of an unresolved CONFLICT is missing from proposals."""
    node = ResponseSynthesizerNode()

    critique = PeerCritique(
        reviewer_agent_id="specialist_b",
        target_agent_id="specialist_missing",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="dependency_order",
        critique="Target agent specification is invalid.",
        proposed_resolution="Revert to standard template.",
        resolved=False,
    )

    delib_state = {
        "panel_id": "missing_target_panel",
        "shared_constraints": [],
        "proposals": {1: {}},
        "active_proposals": {},
        "critiques": {1: [critique.model_dump()]},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state}
    output = node.synthesize_deliberation(state)

    assert "## Minority Report: Unresolved Conflicts" in output
    assert "### Conflict: dependency_order (specialist_missing vs specialist_b)" in output
    assert "### Option A (specialist_missing Position)" in output
    assert "- **Position**: Specialist proposed action" in output
    assert "### Option B (specialist_b Position)" in output


# ============================================================================
# 4. Mixed Taint Flag Propagation Stress Tests
# ============================================================================


def test_stress_mixed_taint_propagation():
    """Adversarially tests mixed taint propagation: 2 tainted agents, 2 clean agents."""
    node = ResponseSynthesizerNode()

    props = {
        "agent_clean_1": AgentProposal(
            agent_id="agent_clean_1",
            round_num=1,
            scope="scope_alpha",
            summary="Clean proposal 1 from trusted sources.",
            recommendations=["Standard operation 1"],
            tainted=False,
        ),
        "agent_tainted_1": AgentProposal(
            agent_id="agent_tainted_1",
            round_num=1,
            scope="scope_alpha",
            summary="Proposal based on external untrusted input document.",
            recommendations=["Cautious operation 2"],
            tainted=True,
        ),
        "agent_clean_2": AgentProposal(
            agent_id="agent_clean_2",
            round_num=1,
            scope="scope_alpha",
            summary="Clean proposal 2 from trusted sources.",
            recommendations=["Standard operation 3"],
            tainted=False,
        ),
        "agent_tainted_2": AgentProposal(
            agent_id="agent_tainted_2",
            round_num=1,
            scope="scope_alpha",
            summary="Proposal containing scraped third-party data.",
            recommendations=["External operation 4"],
            tainted=True,
        ),
    }

    delib_state = {
        "panel_id": "taint_panel",
        "shared_constraints": [],
        "proposals": {1: {k: v.model_dump() for k, v in props.items()}},
        "active_proposals": {k: v.model_dump() for k, v in props.items()},
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state, "tainted": True}
    output = node.synthesize_deliberation(state)

    # Check individual agent warning banners
    assert "> ⚠️ **Warning**: Recommendations from agent 'agent_tainted_1' are based partly on content from an untrusted source." in output
    assert "> ⚠️ **Warning**: Recommendations from agent 'agent_tainted_2' are based partly on content from an untrusted source." in output
    assert "from agent 'agent_clean_1'" not in output
    assert "from agent 'agent_clean_2'" not in output

    # Check section headers tag only tainted agents
    assert "#### Agent Tainted 1 Perspective [⚠️ Untrusted Source]" in output
    assert "#### Agent Tainted 2 Perspective [⚠️ Untrusted Source]" in output
    assert "#### Agent Clean 1 Perspective\n" in output
    assert "#### Agent Clean 2 Perspective\n" in output
    assert "#### Agent Clean 1 Perspective [" not in output
    assert "#### Agent Clean 2 Perspective [" not in output


def test_stress_run_level_taint_without_tainted_proposals():
    """Tests when run is tainted (state['tainted'] = True) but no individual proposal is flagged."""
    node = ResponseSynthesizerNode()

    props = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=1,
            scope="scope_alpha",
            summary="Proposal A.",
            recommendations=["Task A"],
            tainted=False,
        ),
        "agent_b": AgentProposal(
            agent_id="agent_b",
            round_num=1,
            scope="scope_alpha",
            summary="Proposal B.",
            recommendations=["Task B"],
            tainted=False,
        ),
    }

    delib_state = {
        "panel_id": "run_taint_panel",
        "shared_constraints": [],
        "proposals": {1: {k: v.model_dump() for k, v in props.items()}},
        "active_proposals": {k: v.model_dump() for k, v in props.items()},
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state, "tainted": True}
    output = node.synthesize_deliberation(state)

    # General untrusted banner emitted
    assert "> ⚠️ **Warning**: Recommendations in this plan are based partly on content from an untrusted source." in output
    # No individual agent bracket tags
    assert "[⚠️ Untrusted Source]" not in output


def test_stress_clean_untainted_run():
    """Verifies that an untainted run has zero warning banners and zero taint tags."""
    node = ResponseSynthesizerNode()

    props = {
        "agent_a": AgentProposal(
            agent_id="agent_a",
            round_num=1,
            scope="scope_alpha",
            summary="Clean proposal A.",
            recommendations=["Task A"],
            tainted=False,
        ),
        "agent_b": AgentProposal(
            agent_id="agent_b",
            round_num=1,
            scope="scope_alpha",
            summary="Clean proposal B.",
            recommendations=["Task B"],
            tainted=False,
        ),
    }

    delib_state = {
        "panel_id": "clean_panel",
        "shared_constraints": [],
        "proposals": {1: {k: v.model_dump() for k, v in props.items()}},
        "active_proposals": {k: v.model_dump() for k, v in props.items()},
        "critiques": {},
        "rounds_used": 1,
    }

    state = {"deliberation_state": delib_state, "tainted": False}
    output = node.synthesize_deliberation(state)

    assert "⚠️" not in output
    assert "Untrusted Source" not in output


# ============================================================================
# 5. Degraded Single-Agent Fallback Stress Tests
# ============================================================================


def test_stress_degraded_fallback_with_multiple_missing_agents():
    """Tests degraded fallback when multiple peer specialists failed schema validation."""
    node = ResponseSynthesizerNode()

    delib_state = {
        "panel_id": "degraded_panel",
        "degraded": True,
        "missing_agents": ["specialist_beta", "specialist_gamma", "specialist_delta"],
    }

    single_output = (
        "Specialist Alpha proposal: Proceed with primary pipeline configuration.\n\n"
        "DISCLAIMER: Temporary constituent disclaimer."
    )

    state = {
        "deliberation_state": delib_state,
        "output": single_output,
    }

    output = node.synthesize_deliberation(state)

    assert "# Deliberation Plan (for stakeholder review)" in output
    assert "*Note: Multi-agent deliberation degraded to single-agent answer due to insufficient valid proposals. Missing agents: specialist_beta, specialist_gamma, specialist_delta.*" in output
    assert "Specialist Alpha proposal: Proceed with primary pipeline configuration." in output
    # Verifies constituent disclaimer was stripped
    assert "Temporary constituent disclaimer" not in output
    # Verifies canonical disclaimer appended
    assert output.endswith(CANONICAL_DISCLAIMER)


def test_stress_degraded_fallback_empty_missing_agents_and_none_output():
    """Tests degraded fallback when missing_agents is empty and state['output'] is None."""
    node = ResponseSynthesizerNode()

    delib_state = {
        "panel_id": "degraded_empty_panel",
        "degraded": True,
        "missing_agents": [],
    }

    state = {
        "deliberation_state": delib_state,
        "output": None,
    }

    output = node.synthesize_deliberation(state)

    assert "# Deliberation Plan (for stakeholder review)" in output
    # Checks clean note without dangling spaces or periods
    assert "*Note: Multi-agent deliberation degraded to single-agent answer due to insufficient valid proposals.*" in output
    assert "Multi-agent deliberation degraded to single-agent answer due to insufficient valid proposals." in output
    assert output.endswith(CANONICAL_DISCLAIMER)


# ============================================================================
# 6. Union Safety Policy Fail-Closed and Hard Refusal Stress Tests
# ============================================================================


def test_stress_union_safety_policy_5_pack_aggregation():
    """Stress-tests 5-pack UnionSafetyPolicy with mixed soft, hard, and clean evaluations."""
    p_clean = MockAdversarialSafetyPolicy(domain_name="pack_clean", forbidden_keywords=())
    p_soft_1 = MockAdversarialSafetyPolicy(
        domain_name="pack_soft_1",
        forbidden_keywords=["soft_trigger_1"],
        is_hard=False,
        refusal_reason="boundary_violation:soft_1",
    )
    p_soft_2 = MockAdversarialSafetyPolicy(
        domain_name="pack_soft_2",
        forbidden_keywords=["soft_trigger_2"],
        is_hard=False,
        refusal_reason="boundary_violation:soft_2",
    )
    p_hard = MockAdversarialSafetyPolicy(
        domain_name="pack_hard",
        forbidden_keywords=["hard_trigger"],
        is_hard=True,
        refusal_reason="forbidden_intent:hard_prohibited",
    )
    p_emergency = MockAdversarialSafetyPolicy(
        domain_name="pack_emergency",
        forbidden_keywords=(),
        emergency_keyword="acute_failure",
    )

    union = UnionSafetyPolicy([p_clean, p_soft_1, p_soft_2, p_hard, p_emergency])

    # 1. Clean text passes
    v_clean = union.check_output("Safe operational execution plan.")
    assert not v_clean.refused

    # 2. Single soft refusal produces soft refusal verdict
    v_soft = union.check_output("Plan includes soft_trigger_1.")
    assert v_soft.refused
    assert not v_soft.is_hard
    assert v_soft.reason == "boundary_violation:soft_1"

    # 3. Multiple soft refusals produce soft refusal verdict
    v_multi_soft = union.check_output("Plan includes soft_trigger_1 and soft_trigger_2.")
    assert v_multi_soft.refused
    assert not v_multi_soft.is_hard

    # 4. Mixed soft and hard triggers produce HARD refusal verdict (hard precedence)
    v_mixed = union.check_output("Plan includes soft_trigger_1 and hard_trigger.")
    assert v_mixed.refused
    assert v_mixed.is_hard
    assert v_mixed.reason == "forbidden_intent:hard_prohibited"

    # 5. Emergency detection across constituent policies
    assert union.check_emergency("Everything is running normal.") is None
    em = union.check_emergency("System encountered an acute_failure event.")
    assert em is not None
    assert em.detected
    assert "Critical emergency alert raised" in em.referral_message

    # 6. Hard refusal reason query
    assert union.is_hard_refusal_reason("forbidden_intent:hard_prohibited")
    assert not union.is_hard_refusal_reason("boundary_violation:soft_1")
    assert not union.is_hard_refusal_reason("unknown_reason")


@pytest.mark.asyncio
async def test_stress_output_guardrail_with_dynamically_injected_deliberation_policies():
    """Verifies that OutputGuardrailNode aggregates safety policies across state, node, and deliberation proposals."""
    node_policy = MockAdversarialSafetyPolicy(
        domain_name="base_node_policy",
        forbidden_keywords=["unauthorized_action"],
        is_hard=True,
    )
    guardrail = OutputGuardrailNode(safety_policy=node_policy)

    state_policy = MockAdversarialSafetyPolicy(
        domain_name="state_extra_policy",
        forbidden_keywords=["restricted_resource"],
        is_hard=False,
    )

    delib_state = {
        "panel_id": "guardrail_panel",
        "active_proposals": {
            "specialist_a": {"scope": "scope_alpha", "summary": "Proposal A"},
            "specialist_b": {"scope": "scope_beta", "summary": "Proposal B"},
        },
    }

    # Clean output passes
    state_clean = {
        "output": "Normal synthesized proposal text.",
        "safety_policies": [state_policy],
        "deliberation_state": delib_state,
    }
    res_clean = await guardrail.execute(state_clean)
    assert not res_clean.get("refused")

    # Output violating state policy triggers refusal
    state_violating = {
        "output": "Synthesized text mentioning restricted_resource usage.",
        "safety_policies": [state_policy],
        "deliberation_state": delib_state,
    }
    res_violating = await guardrail.execute(state_violating)
    assert res_violating.get("refused")
    assert res_violating.get("is_refusal")
    assert res_violating.get("next_step") == "reflection"


# ============================================================================
# 7. End-to-End Node Execution with Zero-Body Audit Logging & Suggestions
# ============================================================================


@pytest.mark.asyncio
async def test_stress_response_synthesizer_node_execute_full_lifecycle(tmp_path):
    """Stress-tests the full async execute() method of ResponseSynthesizerNode including audit logging."""
    import os
    from yarvelle_core.config import settings

    audit_log_file = tmp_path / "test_stress_audit.log"
    old_log_path = settings.audit_log_path
    settings.audit_log_path = str(audit_log_file)

    try:
        node = ResponseSynthesizerNode()

        c = SharedConstraint(id="quota_work", description="Work quota", unit="hours", limit_value=40.0, limit_source="user")
        prop = AgentProposal(
            agent_id="specialist_1",
            round_num=1,
            scope="scope_alpha",
            summary="Operational blueprint summary.",
            recommendations=["Initiate step 1"],
            resource_claims={"quota_work": 30.0},
        )

        delib_state = {
            "panel_id": "lifecycle_panel",
            "shared_constraints": [c.model_dump()],
            "proposals": {1: {"specialist_1": prop.model_dump()}},
            "active_proposals": {"specialist_1": prop.model_dump()},
            "critiques": {},
            "rounds_used": 1,
        }

        state: Dict[str, Any] = {
            "deliberation_state": delib_state,
            "thread_id": "stress_thread_999",
            "prompt": "Coordinate operational schedule",
            "audit_events": [],
        }

        result = await node.execute(state)

        # Output verification
        assert "output" in result
        assert "# Deliberation Plan (for stakeholder review)" in result["output"]
        assert "| quota_work | 40.0 hours (user) | 30.0 hours | Within limit |" in result["output"]
        assert result["output"].endswith(CANONICAL_DISCLAIMER)

        # Follow-up suggestion chips verification
        assert "follow_up_suggestions" in result
        assert "Review coordinated deliberation plan with team" in result["follow_up_suggestions"]
        assert "Evaluate resource allocation constraints" in result["follow_up_suggestions"]
        assert "Review open minority report options and amendment notes" in result["follow_up_suggestions"]

        # Audit events in state
        assert len(result["audit_events"]) == 1
        event = result["audit_events"][0]
        assert event["event"] == "synthesis"
        assert event["allowed"] is True
        assert event["thread_id"] == "stress_thread_999"

        # Audit file persistence on disk
        assert audit_log_file.exists()
        content = audit_log_file.read_text(encoding="utf-8")
        assert "synthesis" in content
        assert "stress_thread_999" in content

    finally:
        settings.audit_log_path = old_log_path
