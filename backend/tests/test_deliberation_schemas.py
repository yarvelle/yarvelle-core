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

"""Unit tests for multi-agent deliberation schemas, blackboard state, and pack panel specs (M1).

Verifies ADR 0001 Phase 1 data contracts:
- ExecutionMode.DELIBERATE enum and ExecutionPlan integration
- SharedConstraint schema, slug validation, and mandatory limit_source validation
- DeliberationBudget defaults and bounds (1..4 rounds, positive timeouts and tokens)
- DeliberationConfig critique modes (per_agent vs batched) and consensus_threshold absence
- TypedClaim anti-smuggling slug regex and closed domain-neutral unit allowlist
- StagedAction and AgentProposal schemas
- PeerCritique Disagree-or-Commit validation (stances, self-critique rejection, bare agreement rejection)
- PackProvidesSpec panel declarations and Phase 1 single-domain invariant validation
- Complete removal of hardcoded domain keywords from OrchestratorNode._route()
- Canonical JSON schema committed freshness with zero drift
"""

from __future__ import annotations

from datetime import date
import difflib
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest
from pydantic import ValidationError

from yarvelle_core.pack.spec import (
    PackManifest,
    PackPanelSpec,
    PackProvidesSpec,
    PackSpec,
    PanelDefaultConstraintSpec,
)
from yarvelle_core.pack.validator import PackValidationError, validate_pack_spec
from yarvelle_core.schemas.generator import generate_json_schema
from yarvelle_core.schemas.manifest import AgentManifest
from yarvelle_core.schemas.plan import (
    AgentTask,
    DeliberationBudget,
    DeliberationConfig,
    ExecutionMode,
    ExecutionPlan,
    SharedConstraint,
)
from yarvelle_core.workflows.nodes.orchestrator_node import OrchestratorNode
from yarvelle_core.workflows.state import (
    ALLOWED_CLAIM_UNITS,
    AgentProposal,
    AgentState,
    CritiqueStance,
    PeerCritique,
    StagedAction,
    TypedClaim,
    create_initial_state,
)


# ============================================================================
# 1. ExecutionMode.DELIBERATE
# ============================================================================


def test_execution_mode_deliberate():
    """Verify ExecutionMode.DELIBERATE definition, value, and ExecutionPlan serialization."""
    assert ExecutionMode.DELIBERATE == "deliberate"
    assert ExecutionMode.DELIBERATE.value == "deliberate"
    assert ExecutionMode("deliberate") is ExecutionMode.DELIBERATE

    # Verify plan integration
    task = AgentTask(agent_id="specialist_a", task_description="Perform analysis")
    plan = ExecutionPlan(
        mode=ExecutionMode.DELIBERATE,
        target_agents=["specialist_a", "specialist_b"],
        tasks=[task],
        reasoning="Multi-agent panel required for trade-off resolution.",
    )
    assert plan.mode == ExecutionMode.DELIBERATE
    assert plan["mode"] == "deliberate"
    assert plan.to_dict()["mode"] == "deliberate"

    # Verify deserialization from dict
    raw_dict = {
        "mode": "deliberate",
        "target_agents": ["specialist_a", "specialist_b"],
        "tasks": [{"agent_id": "specialist_a", "task_description": "Initial task"}],
    }
    validated = ExecutionPlan.model_validate(raw_dict)
    assert validated.mode is ExecutionMode.DELIBERATE


# ============================================================================
# 2. SharedConstraint Validation & Limit Source Requirements
# ============================================================================


def test_shared_constraint_validation():
    """Verify SharedConstraint ID slug regex and field validations."""
    # Valid constraint definitions
    c1 = SharedConstraint(
        id="weekly_time_budget",
        description="Weekly total allowable time",
        unit="hours",
        limit_value=20.0,
        limit_source="user",
    )
    assert c1.id == "weekly_time_budget"
    assert c1.unit == "hours"
    assert c1.limit_value == 20.0
    assert c1.limit_source == "user"

    c2 = SharedConstraint(
        id="capacity_units_10",
        description="Maximum execution units",
        unit="units",
        limit_value=100.0,
        limit_source="profile",
    )
    assert c2.limit_source == "profile"

    # Slug regex failures (must match ^[a-z0-9_-]{1,64}$)
    invalid_ids = [
        "Weekly Budget",  # uppercase and space
        "weekly budget",  # space
        "weekly/budget",  # slash
        "weekly$budget",  # dollar sign
        "a" * 65,  # exceeds 64 characters
        "",  # empty string
    ]
    for bad_id in invalid_ids:
        with pytest.raises(ValidationError):
            SharedConstraint(
                id=bad_id,
                description="Test constraint",
                unit="hours",
                limit_value=10.0,
                limit_source="user",
            )


def test_shared_constraint_requires_limit_source():
    """Verify SharedConstraint requires limit_source ('user' or 'profile') when limit_value is set."""
    # Valid cases: limit_value set with explicit valid source
    SharedConstraint(
        id="time_limit",
        description="Time limit",
        unit="hours",
        limit_value=15.0,
        limit_source="user",
    )
    SharedConstraint(
        id="time_limit",
        description="Time limit",
        unit="hours",
        limit_value=0.0,
        limit_source="profile",
    )

    # Valid case: limit_value is None (unverified / unknown limit)
    c_none = SharedConstraint(
        id="time_limit",
        description="Time limit",
        unit="hours",
        limit_value=None,
        limit_source=None,
    )
    assert c_none.limit_value is None
    assert c_none.limit_source is None

    # Invalid: limit_value is set but limit_source is None
    with pytest.raises(ValidationError) as exc_info:
        SharedConstraint(
            id="time_limit",
            description="Time limit",
            unit="hours",
            limit_value=15.0,
            limit_source=None,
        )
    assert "limit_source" in str(exc_info.value).lower()

    # Invalid: limit_value is set but limit_source is invalid (e.g. model-sourced)
    with pytest.raises(ValidationError):
        SharedConstraint(
            id="time_limit",
            description="Time limit",
            unit="hours",
            limit_value=15.0,
            limit_source="model",  # Models must NEVER source limits!
        )


def test_shared_constraint_limit_source_disallowed_when_limit_value_none():
    """Verify limit_source cannot be set when limit_value is None."""
    with pytest.raises(ValidationError) as exc_info:
        SharedConstraint(
            id="time_limit",
            description="Time limit",
            unit="hours",
            limit_value=None,
            limit_source="user",
        )
    assert "cannot be set when limit_value is none" in str(exc_info.value).lower()


# ============================================================================
# 3. DeliberationBudget Defaults and Bounds
# ============================================================================


def test_deliberation_budget_bounds():
    """Verify DeliberationBudget defaults and strict boundary invariants."""
    # Defaults
    budget = DeliberationBudget()
    assert budget.max_rounds == 2
    assert budget.max_wall_clock_s == 120.0
    assert budget.max_total_tokens == 40_000

    # Bounds for max_rounds: 1..4
    for r in (1, 2, 3, 4):
        b = DeliberationBudget(max_rounds=r)
        assert b.max_rounds == r

    # Rejection of invalid rounds
    for bad_r in (0, -1, 5, 10):
        with pytest.raises(ValidationError):
            DeliberationBudget(max_rounds=bad_r)

    # Rejection of non-positive timeouts and tokens
    with pytest.raises(ValidationError):
        DeliberationBudget(max_wall_clock_s=0.0)
    with pytest.raises(ValidationError):
        DeliberationBudget(max_wall_clock_s=-10.0)

    with pytest.raises(ValidationError):
        DeliberationBudget(max_total_tokens=0)
    with pytest.raises(ValidationError):
        DeliberationBudget(max_total_tokens=-500)


# ============================================================================
# 4. DeliberationConfig Critique Mode & Consensus Threshold Absence
# ============================================================================


def test_deliberation_config_critique_mode():
    """Verify DeliberationConfig critique modes (per_agent vs batched) and no consensus_threshold."""
    # Defaults
    cfg = DeliberationConfig()
    assert cfg.panel_id is None
    assert cfg.moderator_agent_id == "orchestrator"
    assert cfg.budget.max_rounds == 2
    assert cfg.critique_mode == "per_agent"
    assert cfg.shared_constraints == []

    # Valid critique modes
    cfg_per = DeliberationConfig(critique_mode="per_agent")
    assert cfg_per.critique_mode == "per_agent"

    cfg_batch = DeliberationConfig(critique_mode="batched")
    assert cfg_batch.critique_mode == "batched"

    # Invalid critique mode
    with pytest.raises(ValidationError):
        DeliberationConfig(critique_mode="freeform")

    # Strict invariant: no consensus_threshold field exists on DeliberationConfig
    assert "consensus_threshold" not in DeliberationConfig.model_fields


def test_deliberation_config_extra_forbid():
    """Verify DeliberationConfig rejects consensus_threshold and extra fields via extra='forbid'."""
    with pytest.raises(ValidationError):
        DeliberationConfig.model_validate({"consensus_threshold": 0.8})


# ============================================================================
# 5. TypedClaim Anti-Smuggling Slug Regex
# ============================================================================


def test_typed_claim_slug_regex_anti_smuggling():
    """Verify TypedClaim.key strictly matches ^[a-z0-9_-]{1,64}$ to prevent text smuggling."""
    # Valid slugs pass
    valid_keys = [
        "allocated_hours",
        "quota-limit",
        "metric_score_1",
        "a",
        "x" * 64,
    ]
    for key in valid_keys:
        claim = TypedClaim(
            kind="amount",
            key=key,
            value=10.0,
            unit="hours",
            source_scope="scope_alpha.metrics",
        )
        assert claim.key == key

    # Invalid slugs must fail (spaces, uppercase, newlines, long strings, punctuation)
    invalid_keys = [
        "allocated hours",  # contains space
        "AllocatedHours",  # uppercase
        "allocated\nhours",  # newline
        "key;DROP TABLE;",  # SQL-like injection
        "<script>alert(1)</script>",  # HTML tags
        "recommendation is to approve waiver",  # smuggling natural language with spaces
        "x" * 65,  # exceeds 64 characters
        "",  # empty string
    ]
    for bad_key in invalid_keys:
        with pytest.raises(ValidationError):
            TypedClaim(
                kind="amount",
                key=bad_key,
                value=10.0,
                unit="hours",
                source_scope="scope_alpha.metrics",
            )


# ============================================================================
# 6. TypedClaim Closed Unit Allowlist
# ============================================================================


def test_typed_claim_closed_unit_allowlist():
    """Verify TypedClaim.unit is validated against domain-neutral ALLOWED_CLAIM_UNITS."""
    # Verify ALLOWED_CLAIM_UNITS contains only domain-neutral units
    assert isinstance(ALLOWED_CLAIM_UNITS, frozenset)
    expected_units = {
        "hours",
        "minutes",
        "seconds",
        "days",
        "weeks",
        "months",
        "years",
        "units",
        "count",
        "items",
        "points",
        "percent",
        "percentage",
        "ratio",
        "score",
        "rate",
        "hours/week",
        "minutes/day",
    }
    assert expected_units.issubset(ALLOWED_CLAIM_UNITS)

    # Valid allowed units
    for unit in ("hours", "units", "items", "percent", "hours/week"):
        c = TypedClaim(
            kind="amount",
            key="resource_used",
            value=25.0,
            unit=unit,
            source_scope="scope_alpha.tasks",
        )
        assert c.unit == unit

    # Unregistered or domain-specific units must fail
    disallowed_units = [
        "USD",
        "EUR",
        "mg",
        "mg/dL",
        "furlongs",
        "custom_pack_unit",
        "free text unit description",
    ]
    for bad_unit in disallowed_units:
        with pytest.raises(ValidationError):
            TypedClaim(
                kind="amount",
                key="resource_used",
                value=25.0,
                unit=bad_unit,
                source_scope="scope_alpha.tasks",
            )

    # Amount and quantity kinds require a non-null unit
    with pytest.raises(ValidationError):
        TypedClaim(
            kind="amount",
            key="resource_used",
            value=25.0,
            unit=None,
            source_scope="scope_alpha.tasks",
        )

    with pytest.raises(ValidationError):
        TypedClaim(
            kind="quantity",
            key="items_total",
            value=5.0,
            unit=None,
            source_scope="scope_alpha.tasks",
        )

    # Boolean and date_window kinds allow unit=None
    b_claim = TypedClaim(
        kind="boolean",
        key="is_ready",
        value=True,
        unit=None,
        source_scope="scope_alpha.tasks",
    )
    assert b_claim.value is True

    d_claim = TypedClaim(
        kind="date_window",
        key="window_period",
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 31),
        unit=None,
        source_scope="scope_alpha.tasks",
    )
    assert d_claim.window_start == date(2026, 1, 1)

    # Inverted date window fails
    with pytest.raises(ValidationError):
        TypedClaim(
            kind="date_window",
            key="window_period",
            window_start=date(2026, 2, 1),
            window_end=date(2026, 1, 1),
            source_scope="scope_alpha.tasks",
        )


# ============================================================================
# 7. PeerCritique Disagree-or-Commit Validation
# ============================================================================


def test_peer_critique_disagree_or_commit_validation():
    """Verify Disagree-or-Commit rules: stances, self-critique rejection, and bare agreement rejection."""
    # Stances enum
    assert CritiqueStance.ENDORSE == "endorse"
    assert CritiqueStance.COMPLEMENT == "complement"
    assert CritiqueStance.AMEND == "amend"
    assert CritiqueStance.CONFLICT == "conflict"

    # Valid substantive endorsement
    valid_endorse = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.ENDORSE,
        issue_type="synergy",
        critique="Proposal aligns with prerequisite step 1; resource utilization is within bounds.",
        proposed_resolution="Commit to proposal as specified.",
    )
    assert valid_endorse.stance is CritiqueStance.ENDORSE

    # Valid conflict critique
    valid_conflict = PeerCritique(
        reviewer_agent_id="specialist_a",
        target_agent_id="specialist_b",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Allocated 35 hours exceeds maximum shared constraint of 20 hours.",
        proposed_resolution="Reduce step allocation to 10 hours.",
    )
    assert valid_conflict.stance is CritiqueStance.CONFLICT

    # Self-critique rejection: reviewer cannot critique self
    with pytest.raises(ValidationError) as exc_self:
        PeerCritique(
            reviewer_agent_id="specialist_a",
            target_agent_id="specialist_a",
            round_num=1,
            stance=CritiqueStance.ENDORSE,
            issue_type="synergy",
            critique="Self endorsement is invalid.",
            proposed_resolution="Commit.",
        )
    assert "reviewer" in str(exc_self.value).lower() or "target" in str(exc_self.value).lower()

    # Bare agreement rejection: empty or trivial agreement rejected
    bare_critiques = [
        "",
        "   ",
        "agree",
        "looks good",
        "lgtm",
        "ok",
    ]
    for bare in bare_critiques:
        with pytest.raises(ValidationError):
            PeerCritique(
                reviewer_agent_id="specialist_a",
                target_agent_id="specialist_b",
                round_num=1,
                stance=CritiqueStance.ENDORSE,
                issue_type="synergy",
                critique=bare,
                proposed_resolution="Commit.",
            )


# ============================================================================
# 8. Pack Panel Spec: Same-Domain Panels Pass
# ============================================================================


def test_pack_provides_spec_panels_same_domain_pass():
    """Verify that PackProvidesSpec declaring same-domain panels passes validation."""
    panel_constraint = PanelDefaultConstraintSpec(
        id="weekly_hours_cap",
        description="Maximum weekly hours for panel execution",
        unit="hours",
    )
    panel_spec = PackPanelSpec(
        id="alpha_coordination_panel",
        title="Alpha Coordination Panel",
        description="Multi-agent coordination across domain_alpha tasks.",
        agents=["domain_alpha.specialist_a", "domain_alpha.specialist_b"],
        max_rounds=2,
        default_constraints=[panel_constraint],
    )

    pack_spec = PackSpec(
        id="pack_alpha",
        name="Pack Alpha",
        version="0.1.0",
        domain="domain_alpha",
        requires_core=">=0.1.0",
        owned_scopes=["domain_alpha.tasks", "domain_alpha.metrics"],
        risk_tier_max="T1",
        provides=PackProvidesSpec(
            panels=[panel_spec],
        ),
    )

    # Semantic validation must pass without error
    validate_pack_spec(pack_spec)


# ============================================================================
# 9. Pack Panel Spec: Cross-Domain Panels Rejected in Phase 1
# ============================================================================


def test_pack_provides_spec_panels_cross_domain_rejected():
    """Verify that in Phase 1, declaring cross-domain panel members raises PackValidationError."""
    panel_spec = PackPanelSpec(
        id="cross_domain_panel",
        title="Cross Domain Panel",
        description="Cross domain panel attempting cross-scope membership in Phase 1.",
        agents=["domain_alpha.specialist_a", "domain_beta.specialist_foreign"],
        max_rounds=2,
    )

    pack_spec = PackSpec(
        id="pack_alpha",
        name="Pack Alpha",
        version="0.1.0",
        domain="domain_alpha",
        requires_core=">=0.1.0",
        owned_scopes=["domain_alpha.tasks"],
        risk_tier_max="T1",
        provides=PackProvidesSpec(
            panels=[panel_spec],
        ),
    )

    with pytest.raises(PackValidationError) as exc_info:
        validate_pack_spec(pack_spec)

    err_str = str(exc_info.value).lower()
    assert "single-domain" in err_str or "cross-domain" in err_str or "domain_beta" in err_str


# ============================================================================
# 10. Orchestrator Routing Purge: No Hardcoded Domain Keywords
# ============================================================================


def test_orchestrator_route_removes_hardcoded_domain_keywords():
    """Verify that OrchestratorNode._route has no hardcoded domain keywords or condition tuples."""
    source = inspect.getsource(OrchestratorNode._route)

    # Keywords that must NOT be present in core routing
    disallowed_identifiers = [
        "auth_keywords",
        "condition_patterns",
        "specialty_keywords",
        "cardiology-guide",
        "nephrology-guide",
        "pulmonology-guide",
        "prior-auth-navigator",
        "formulary-guide",
        "claims-appeals-guide",
        "benefits-guide",
    ]

    for identifier in disallowed_identifiers:
        assert identifier not in source, f"Found hardcoded domain identifier '{identifier}' in OrchestratorNode._route!"


def test_orchestrator_route_mode_deliberate_and_parallel():
    """Verify OrchestratorNode._route produces DELIBERATE and PARALLEL execution plans."""
    node = OrchestratorNode(model=None)
    state = {
        "deliberation_config": {"panel_id": "panel_alpha"},
    }
    candidate_a = AgentManifest(
        id="specialist_a",
        title="Specialist A",
        description="First specialist",
        persona="First specialist persona",
        category="general",
    )
    candidate_b = AgentManifest(
        id="specialist_b",
        title="Specialist B",
        description="Second specialist",
        persona="Second specialist persona",
        category="general",
    )
    plan_delib = node._route(
        target_agent="specialist_a",
        prompt_text="Please deliberate on the proposed approach",
        state=state,
        candidates=[candidate_a, candidate_b],
    )
    assert plan_delib.mode == ExecutionMode.DELIBERATE
    assert plan_delib.deliberation_config is not None
    assert plan_delib.target_agents == ["specialist_a", "specialist_b"]

    plan_parallel = node._route(
        target_agent="specialist_a",
        prompt_text="Please coordinate between both specialists",
        state={},
        candidates=[candidate_a, candidate_b],
    )
    assert plan_parallel.mode == ExecutionMode.PARALLEL
    assert plan_parallel.target_agents == ["specialist_a", "specialist_b"]

    plan_single = node._route(
        target_agent="specialist_a",
        prompt_text="Execute standard task",
        state={},
        candidates=[candidate_a, candidate_b],
    )
    assert plan_single.mode == ExecutionMode.SINGLE
    assert plan_single.target_agents == ["specialist_a"]


# ============================================================================
# 11. Canonical JSON Schema Freshness Check
# ============================================================================


def test_canonical_schemas_committed_freshness():
    """Verify canonical JSON schemas on disk are fresh and match Pydantic models with 0 drift."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backend_dir = Path(__file__).resolve().parent.parent
    target_dirs = [
        repo_root / "schemas",
        backend_dir / "src" / "yarvelle_core" / "schemas",
    ]

    schema_specs = [
        (
            "pack.schema.json",
            PackManifest,
            "Yarvelle Pack Manifest Schema (Pack API v1)",
            "https://schemas.yarvelle.org/v1/pack.schema.json",
        ),
    ]

    for target_dir in target_dirs:
        for filename, model_cls, title, schema_id in schema_specs:
            schema_file = target_dir / filename
            assert schema_file.exists(), f"Schema file {schema_file} missing."

            committed_text = schema_file.read_text(encoding="utf-8")
            live_schema = generate_json_schema(model_cls, title=title, schema_id=schema_id)
            expected_text = json.dumps(live_schema, indent=2) + "\n"

            diff = list(
                difflib.unified_diff(
                    committed_text.splitlines(keepends=True),
                    expected_text.splitlines(keepends=True),
                    fromfile=f"committed/{filename}",
                    tofile=f"live/{filename}",
                )
            )
            assert not diff, (
                f"Schema drift detected in {schema_file}!\n"
                f"{''.join(diff)}\n"
                "Remediation: Run 'python3 scripts/generate_schemas.py' and commit."
            )


# ============================================================================
# 12. Supplementary Schema Checks: StagedAction, AgentProposal, AgentState
# ============================================================================


def test_staged_action_schema_validation():
    """Verify StagedAction schema risk_tier validation and domain-neutral attributes."""
    action = StagedAction(
        agent_id="specialist_a",
        tool_name="read_resource",
        tool_args={"resource_id": "res_123"},
        rationale="Inspect initial resource state.",
        risk_tier="read",
    )
    assert action.risk_tier == "read"

    # Invalid risk tier
    with pytest.raises(ValidationError):
        StagedAction(
            agent_id="specialist_a",
            tool_name="drop_db",
            tool_args={},
            rationale="Unsafe action",
            risk_tier="untrusted",  # type: ignore[arg-type]
        )


def test_agent_proposal_schema_validation():
    """Verify AgentProposal resource claims, exported claims, taint, and confidence bounds."""
    proposal = AgentProposal(
        agent_id="specialist_a",
        round_num=1,
        scope="scope_alpha.tasks",
        summary="Proposal for task partitioning",
        recommendations=["Execute partition 1", "Verify checkpoint"],
        resource_claims={"weekly_time_budget": 12.5},
        resource_claim_units={"weekly_time_budget": "hours"},
        confidence=0.85,
        tainted=False,
    )
    assert proposal.confidence == 0.85
    assert proposal.resource_claims["weekly_time_budget"] == 12.5

    # Confidence must be between 0.0 and 1.0
    with pytest.raises(ValidationError):
        AgentProposal(
            agent_id="specialist_a",
            round_num=1,
            scope="scope_alpha.tasks",
            summary="Invalid confidence",
            confidence=1.5,
        )


def test_agent_state_deliberation_channel():
    """Verify deliberation_state channel is defined on AgentState and initialized in create_initial_state."""
    state_annotations = AgentState.__annotations__
    assert "deliberation_state" in state_annotations

    state = create_initial_state()
    assert "deliberation_state" in state
    assert state["deliberation_state"] is None

    custom_state = create_initial_state(deliberation_state={"round_num": 1})
    assert custom_state["deliberation_state"] == {"round_num": 1}
