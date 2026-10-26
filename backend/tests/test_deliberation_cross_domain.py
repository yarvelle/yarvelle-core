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

"""Comprehensive unit tests for Milestone 3 Cross-Domain Panels & Scoped Deliberation.

Verifies ADR 0001 §2.3, §2.9, and §7 Phase 3 requirements:
1. Domain matching helper (is_same_domain) correctly determines scope hierarchy.
2. Same-domain proposals retain full free-text summaries, recommendations, and claims.
3. Cross-domain proposals strip free-text summaries, recommendations, and staged actions (zero leakage).
4. Cross-domain specialists receive only structured TypedClaim items via dual-gate filtering.
5. Dual-gate enforcement: requires BOTH declared_reads AND an active scope grant.
   If either gate fails, the claim is withheld and an undisclosed_constraint claim is emitted.
6. Scope.cross_read audit events are recorded for successful cross-domain claim reads.
7. get_scoped_proposals_for records tamper-evident SHA-256 hash-chained audit events to DB.
8. Peer critique prompt sanitization in doc_critique.py withholds peer free text across domain boundaries.
9. Peer critique in same-domain panels includes full summaries and recommendations.
10. Batched mode critique sanitization in doc_critique.py withholds free text for cross-domain panels.
11. Tool and proposal execution in propose.py and revise.py enforces ScopeContext isolation.
12. Blackboard state serialization roundtrips recorded cross-read metadata.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from pydantic import Field
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.audit.hash_chain import verify_profile_audit_chain
from yarvelle_core.db.models import AuditEventRecord
from yarvelle_core.schemas.plan import DeliberationBudget, DeliberationConfig
from yarvelle_core.scope.context import ScopeContext, scope_context
from yarvelle_core.workflows.deliberation.blackboard import (
    BlackboardManager,
    is_same_domain,
)
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.state import (
    AgentProposal,
    PeerCritique,
    StagedAction,
    TypedClaim,
    create_initial_state,
)

try:
    from tests.fixtures.fake_model import MockChatModel
except ImportError:
    from fixtures.fake_model import MockChatModel


class ScopeTrackingChatModel(MockChatModel):
    """Subclass of MockChatModel that records ScopeContext.get() during invocations."""

    observed_scopes: List[Optional[str]] = Field(default_factory=list)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        ctx = ScopeContext.get()
        self.observed_scopes.append(ctx.scope if ctx else None)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        ctx = ScopeContext.get()
        self.observed_scopes.append(ctx.scope if ctx else None)
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


# ============================================================================
# 1. Domain Matching Helper Tests
# ============================================================================

def test_is_same_domain_evaluation():
    """Verify is_same_domain correctly identifies matching and non-matching domain hierarchies."""
    # Identical scopes
    assert is_same_domain("domain_alpha.tasks", "domain_alpha.tasks") is True
    assert is_same_domain("domain_alpha", "domain_alpha") is True

    # Same top-level prefix
    assert is_same_domain("domain_alpha.tasks", "domain_alpha.reports") is True
    assert is_same_domain("domain_alpha.deep.sub", "domain_alpha.other") is True
    assert is_same_domain("domain_alpha", "domain_alpha.tasks") is True
    assert is_same_domain("domain_alpha.tasks", "domain_alpha") is True

    # Cross-domain mismatches
    assert is_same_domain("domain_alpha.tasks", "domain_beta.tasks") is False
    assert is_same_domain("domain_alpha", "domain_beta") is False
    assert is_same_domain("domain_alpha.one", "domain_gamma.two") is False

    # Empty or None scopes
    assert is_same_domain("", "domain_alpha") is False
    assert is_same_domain("domain_alpha", "") is False
    assert is_same_domain("", "") is False

    # Whitespace scopes fail closed
    assert is_same_domain("   ", "   ") is False
    assert is_same_domain("  ", "domain_alpha") is False
    assert is_same_domain("domain_alpha", "  ") is False

    # Path traversal and leading-dot scopes fail closed
    assert is_same_domain("../a", "../b") is False
    assert is_same_domain("../../etc/passwd", "../foo") is False
    assert is_same_domain("./a", "./b") is False
    assert is_same_domain(".hidden", ".env") is False
    assert is_same_domain(".", ".") is False
    assert is_same_domain("..", "..") is False
    assert is_same_domain("../a", "../a") is False
    assert is_same_domain("a/b.sub", "a/b.sub") is False
    assert is_same_domain("a\\b.sub", "a\\b.sub") is False

    # Non-string and None inputs return False without raising exceptions
    assert is_same_domain(123, "domain_a") is False
    assert is_same_domain("domain_a", 123) is False
    assert is_same_domain("domain_a", None) is False
    assert is_same_domain(None, "domain_a") is False
    assert is_same_domain(None, None) is False


# ============================================================================
# 2. Same-Domain Blackboard Scoped Views (Full Free-Text Retained)
# ============================================================================

def test_same_domain_proposals_retain_full_free_text():
    """Verify same-domain panel members view complete unredacted proposals (ADR 0001 §2.3 Rule 1)."""
    bb = BlackboardManager(panel_id="panel_same_domain")

    prop1 = AgentProposal(
        agent_id="specialist_alpha1",
        round_num=1,
        scope="domain_alpha.analysis",
        summary="Detailed alpha strategic analysis and observations.",
        recommendations=["Execute strategy 1", "Verify metrics 2"],
        resource_claims={"compute_quota": 15.0},
        resource_claim_units={"compute_quota": "units"},
        exported_claims=[
            TypedClaim(kind="quantity", key="compute_quota", value=15.0, unit="units", source_scope="domain_alpha.analysis")
        ],
        dependencies=["service_x"],
        staged_actions=[],
        confidence=0.95,
        provenance=["obs_1", "obs_2"],
    )
    prop2 = AgentProposal(
        agent_id="specialist_alpha2",
        round_num=1,
        scope="domain_alpha.execution",
        summary="Alpha worker execution plan.",
        recommendations=["Run pipeline"],
        resource_claims={"storage_quota": 5.0},
        exported_claims=[],
        staged_actions=[],
    )

    bb.record_proposal(prop1)
    bb.record_proposal(prop2)

    # Reader specialist_alpha2 views proposals
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_alpha2",
        reader_scope="domain_alpha.execution",
    )

    # Must contain specialist_alpha1 but NOT self
    assert "specialist_alpha1" in scoped_views
    assert "specialist_alpha2" not in scoped_views

    view_alpha1 = scoped_views["specialist_alpha1"]
    assert view_alpha1.summary == "Detailed alpha strategic analysis and observations."
    assert view_alpha1.recommendations == ["Execute strategy 1", "Verify metrics 2"]
    assert view_alpha1.resource_claims == {"compute_quota": 15.0}
    assert len(view_alpha1.exported_claims) == 1
    assert view_alpha1.exported_claims[0].key == "compute_quota"

    # Same domain generates no cross-read audit events
    assert cross_read_events == []


# ============================================================================
# 3. Cross-Domain Blackboard Views (Zero Free-Text Leakage)
# ============================================================================

def test_cross_domain_proposals_strip_free_text_and_recommendations():
    """Verify cross-domain panel members receive zero free-text summaries (ADR 0001 §2.3 Rule 2)."""
    bb = BlackboardManager(panel_id="panel_cross_domain")

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.confidential",
        summary="Confidential domain alpha proprietary reasoning and findings.",
        recommendations=["Internal action alpha 1", "Internal action alpha 2"],
        resource_claims={"rate_limit": 50.0},
        resource_claim_units={"rate_limit": "rate"},
        exported_claims=[],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader specialist_beta is in domain_beta with no cross-pack grants
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.auditor",
        declared_reads=[],
        granted_scopes=[],
    )

    assert "specialist_alpha" in scoped_views
    view_alpha = scoped_views["specialist_alpha"]

    # Rule 2 invariants:
    assert view_alpha.summary == ""
    assert view_alpha.recommendations == []
    assert view_alpha.staged_actions == []
    assert view_alpha.resource_claims == {}
    assert view_alpha.exported_claims == []
    assert cross_read_events == []


def test_cross_domain_proposals_withhold_summary_on_path_traversal_scopes():
    """Verify blackboard filtering withholds free-text when scopes contain path traversal or leading dots."""
    bb = BlackboardManager(panel_id="panel_traversal_cross_domain")

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="../secret",
        summary="CONFIDENTIAL_ALPHA_DATA",
        recommendations=["Restricted action"],
        resource_claims={},
        resource_claim_units={},
        exported_claims=[],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # 1. Different traversal scopes
    scoped_views, _ = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="../other",
    )
    assert scoped_views["specialist_alpha"].summary == ""
    assert scoped_views["specialist_alpha"].recommendations == []

    # 2. Identical traversal scopes (still invalid domain prefixes)
    scoped_views_same, _ = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="../secret",
    )
    assert scoped_views_same["specialist_alpha"].summary == ""

    # 3. Leading dot scopes
    scoped_views_dot, _ = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope=".hidden",
    )
    assert scoped_views_dot["specialist_alpha"].summary == ""


# ============================================================================
# 4. Dual-Gate TypedClaim Filtering (ADR 0001 §2.3 Rules 3 & 4)
# ============================================================================

def test_dual_gate_typed_claim_both_gates_granted():
    """Verify TypedClaim is permitted when BOTH declared_reads AND granted_scopes cover source_scope."""
    bb = BlackboardManager(panel_id="panel_dual_gate_success")

    claim_quota = TypedClaim(
        kind="quantity",
        key="quota_allowance",
        value=100.0,
        unit="units",
        source_scope="domain_alpha.network",
    )
    claim_flag = TypedClaim(
        kind="boolean",
        key="high_priority",
        value=True,
        source_scope="domain_alpha.network",
    )

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.network",
        summary="Alpha network configuration.",
        recommendations=["Tune parameters"],
        exported_claims=[claim_quota, claim_flag],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader specialist_beta has both declaration and grant for domain_alpha.*
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.coordinator",
        declared_reads=["domain_alpha.*"],
        granted_scopes=["domain_alpha.*"],
        round_num=1,
    )

    view_alpha = scoped_views["specialist_alpha"]
    assert view_alpha.summary == ""  # Free text stripped
    assert len(view_alpha.exported_claims) == 2

    keys = {c.key: c.value for c in view_alpha.exported_claims}
    assert keys["quota_allowance"] == 100.0
    assert keys["high_priority"] is True

    # Audit event emitted for cross-domain read
    assert len(cross_read_events) == 1
    ev = cross_read_events[0]
    assert ev["reader_agent_id"] == "specialist_beta"
    assert ev["reader_scope"] == "domain_beta.coordinator"
    assert ev["target_agent_id"] == "specialist_alpha"
    assert ev["target_scope"] == "domain_alpha.network"
    assert ev["claim_keys"] == ["high_priority", "quota_allowance"]  # sorted
    assert ev["round_num"] == 1


def test_dual_gate_typed_claim_missing_grant_withheld():
    """Verify claim is withheld with undisclosed_constraint if reader has declared_reads but no active grant."""
    bb = BlackboardManager(panel_id="panel_dual_gate_missing_grant")

    claim_quota = TypedClaim(
        kind="quantity",
        key="quota_allowance",
        value=100.0,
        unit="units",
        source_scope="domain_alpha.network",
    )
    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.network",
        summary="Alpha network details.",
        exported_claims=[claim_quota],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader declared reads for domain_alpha.*, but only has grant for domain_beta.*
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.coordinator",
        declared_reads=["domain_alpha.*"],
        granted_scopes=["domain_beta.*"],
    )

    view_alpha = scoped_views["specialist_alpha"]
    assert view_alpha.summary == ""
    assert len(view_alpha.exported_claims) == 1

    # Undisclosed constraint indicator claim emitted
    indicator = view_alpha.exported_claims[0]
    assert indicator.key == "undisclosed_constraint"
    assert indicator.kind == "boolean"
    assert indicator.value is None
    assert indicator.source_scope == "domain_alpha.network"

    # No cross read audit event because no claim was read
    assert cross_read_events == []


def test_dual_gate_typed_claim_missing_declaration_withheld():
    """Verify claim is withheld with undisclosed_constraint if reader has active grant but forgot declared_reads."""
    bb = BlackboardManager(panel_id="panel_dual_gate_missing_declaration")

    claim_quota = TypedClaim(
        kind="quantity",
        key="quota_allowance",
        value=100.0,
        unit="units",
        source_scope="domain_alpha.network",
    )
    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.network",
        summary="Alpha network details.",
        exported_claims=[claim_quota],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader has grant for domain_alpha.*, but only declared reads for domain_beta.*
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.coordinator",
        declared_reads=["domain_beta.*"],
        granted_scopes=["domain_alpha.*"],
    )

    view_alpha = scoped_views["specialist_alpha"]
    assert len(view_alpha.exported_claims) == 1
    assert view_alpha.exported_claims[0].key == "undisclosed_constraint"
    assert cross_read_events == []


def test_dual_gate_partial_claim_filtering():
    """Verify selective filtering when reader has permissions for some claims but not others."""
    bb = BlackboardManager(panel_id="panel_partial_claims")

    claim_pub = TypedClaim(
        kind="quantity",
        key="public_bandwidth",
        value=500.0,
        unit="rate",
        source_scope="domain_alpha.public",
    )
    claim_priv = TypedClaim(
        kind="quantity",
        key="secret_bandwidth",
        value=50.0,
        unit="rate",
        source_scope="domain_alpha.private",
    )

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.network",
        summary="Alpha summary.",
        exported_claims=[claim_pub, claim_priv],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader declared domain_alpha.* reads, but grant only covers domain_alpha.public
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.coordinator",
        declared_reads=["domain_alpha.*"],
        granted_scopes=["domain_alpha.public"],
    )

    view_alpha = scoped_views["specialist_alpha"]
    # 1 permitted claim + 1 undisclosed_constraint
    assert len(view_alpha.exported_claims) == 2
    claim_keys = [c.key for c in view_alpha.exported_claims]
    assert "public_bandwidth" in claim_keys
    assert "undisclosed_constraint" in claim_keys

    # Audit event records ONLY the permitted claim
    assert len(cross_read_events) == 1
    assert cross_read_events[0]["claim_keys"] == ["public_bandwidth"]


# ============================================================================
# 5. Database Hash-Chained Audit Logging Integration
# ============================================================================

@pytest.mark.asyncio
async def test_get_scoped_proposals_records_cross_read_audit_to_hash_chain(
    async_db_session: AsyncSession,
) -> None:
    """Verify get_scoped_proposals_for logs scope.cross_read events chained to SHA-256 audit ledger."""
    profile_id = "profile_test_cross_read_audit"
    panel_id = "panel_hash_chain_integration"

    bb = BlackboardManager(panel_id=panel_id)

    claim_metrics = TypedClaim(
        kind="quantity",
        key="latency_ms",
        value=12.5,
        unit="seconds",
        source_scope="domain_alpha.services",
    )
    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.services",
        summary="Service proposal.",
        exported_claims=[claim_metrics],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Call get_scoped_proposals_for with an active async database session
    scoped_views = await bb.get_scoped_proposals_for(
        reader_agent_id="specialist_beta",
        reader_scope="domain_beta.auditor",
        declared_reads=["domain_alpha.*"],
        granted_scopes=["domain_alpha.*"],
        round_num=1,
        session=async_db_session,
        profile_id=profile_id,
        actor_user_id="user_admin",
        run_id="run_cross_123",
    )
    await async_db_session.commit()

    assert "specialist_alpha" in scoped_views
    assert len(scoped_views["specialist_alpha"].exported_claims) == 1

    # Query DB to verify the audit event was recorded and chained
    stmt = (
        select(AuditEventRecord)
        .where(AuditEventRecord.profile_id == profile_id)
        .order_by(AuditEventRecord.ts.asc())
        .execution_options(include_all_scopes=True)
    )
    result = await async_db_session.execute(stmt)
    records = result.scalars().all()

    assert len(records) == 1
    r = records[0]
    assert r.event == "scope.cross_read"
    assert r.scope == "domain_beta.auditor"
    assert r.prev_hash is not None
    assert len(r.entry_hash) == 64

    # Verify detail_redacted contains expected payload structure
    detail = json.loads(r.detail_redacted)
    assert detail["reader_agent_id"] == "specialist_beta"
    assert detail["reader_scope"] == "domain_beta.auditor"
    assert detail["target_agent_id"] == "specialist_alpha"
    assert detail["target_scope"] == "domain_alpha.services"
    assert detail["claim_keys"] == ["latency_ms"]
    assert detail["round_num"] == 1
    assert detail["panel_id"] == panel_id

    # Verify the entire profile hash chain validates cryptographically
    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 1
    assert verification["head_hash"] == r.entry_hash


# ============================================================================
# 6. Peer Critique Prompt Sanitization Tests (ADR 0001 §2.3 Rule 6)
# ============================================================================

@pytest.mark.asyncio
async def test_doc_critique_per_agent_sanitizes_cross_domain_peer_prompt():
    """Verify run_peer_critiques in per_agent mode strictly withholds foreign free-text from prompts."""
    mock_model = MockChatModel(model_name="mock-doc-critique")

    # Queue valid JSON critique responses for both agents
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha",
        "target_agent_id": "specialist_beta",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Solid rationale for cross-domain operational parameters.",
        "proposed_resolution": "Proceed as planned.",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_beta",
        "target_agent_id": "specialist_alpha",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Strong alignment with declared latency targets.",
        "proposed_resolution": "Proceed as planned.",
    }])

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.storage",
        summary="CLASSIFIED_ALPHA_SECRET_PROPOSAL_TEXT",
        recommendations=["CONFIDENTIAL_ALPHA_RECOMMENDATION"],
        exported_claims=[
            TypedClaim(kind="quantity", key="storage_quota_mb", value=1024.0, unit="units", source_scope="domain_alpha.storage")
        ],
        staged_actions=[],
    )
    prop_beta = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="domain_beta.compute",
        summary="CLASSIFIED_BETA_SECRET_PROPOSAL_TEXT",
        recommendations=["CONFIDENTIAL_BETA_RECOMMENDATION"],
        exported_claims=[
            TypedClaim(kind="quantity", key="compute_units", value=16.0, unit="count", source_scope="domain_beta.compute")
        ],
        staged_actions=[],
    )

    # Initialize Blackboard with granted scopes so claims are visible
    bb = BlackboardManager(panel_id="panel_critique_test")
    bb.record_proposal(prop_alpha)
    bb.record_proposal(prop_beta)

    with scope_context(
        scope="domain_beta.compute",
        granted_scopes=["domain_alpha.*", "domain_beta.*"],
        declared_reads=["domain_alpha.*", "domain_beta.*"],
    ):
        critiques = await run_peer_critiques(
            proposals=[prop_alpha, prop_beta],
            mode="per_agent",
            model=mock_model,
            round_num=1,
            blackboard=bb,
        )

    assert len(critiques) == 2

    # Inspect all calls made to the language model
    assert len(mock_model.calls) == 2

    for call_info in mock_model.calls:
        msgs = call_info["messages"]
        all_text = " ".join(getattr(m, "content", "") for m in msgs)

        # In per_agent mode between different domains:
        # Neither agent should see the other's free-text proposal summary or recommendations
        if "specialist_alpha" in all_text and "specialist_beta" in all_text:
            # Check the message sent when reviewing the peer
            assert "[Notice: Free-text proposal summary and recommendations are withheld across domain boundaries]" in all_text

        # Zero leakage of foreign secrets across domains
        # When reviewer is beta reviewing alpha:
        if "specialist_alpha (Cross-Domain)" in all_text:
            assert "CLASSIFIED_ALPHA_SECRET_PROPOSAL_TEXT" not in all_text
            assert "CONFIDENTIAL_ALPHA_RECOMMENDATION" not in all_text
            assert "storage_quota_mb: 1024.0 units" in all_text


@pytest.mark.asyncio
async def test_doc_critique_per_agent_allows_same_domain_peer_summary():
    """Verify run_peer_critiques in per_agent mode includes summaries when agents share domain."""
    mock_model = MockChatModel(model_name="mock-doc-critique-same")

    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha1",
        "target_agent_id": "specialist_alpha2",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Endorsing internal alpha workflow step.",
        "proposed_resolution": "Merge proposals.",
    }])
    mock_model.queue_response([{
        "reviewer_agent_id": "specialist_alpha2",
        "target_agent_id": "specialist_alpha1",
        "round_num": 1,
        "stance": "endorse",
        "issue_type": "synergy",
        "critique": "Endorsing internal alpha workflow plan.",
        "proposed_resolution": "Merge proposals.",
    }])

    prop_alpha1 = AgentProposal(
        agent_id="specialist_alpha1",
        round_num=1,
        scope="domain_alpha.one",
        summary="SHARED_ALPHA_INTERNAL_SUMMARY_ONE",
        recommendations=["Internal Step One"],
        exported_claims=[],
        staged_actions=[],
    )
    prop_alpha2 = AgentProposal(
        agent_id="specialist_alpha2",
        round_num=1,
        scope="domain_alpha.two",
        summary="SHARED_ALPHA_INTERNAL_SUMMARY_TWO",
        recommendations=["Internal Step Two"],
        exported_claims=[],
        staged_actions=[],
    )

    bb = BlackboardManager(panel_id="panel_same_critique")
    bb.record_proposal(prop_alpha1)
    bb.record_proposal(prop_alpha2)

    await run_peer_critiques(
        proposals=[prop_alpha1, prop_alpha2],
        mode="per_agent",
        model=mock_model,
        round_num=1,
        blackboard=bb,
    )

    assert len(mock_model.calls) == 2

    call_1_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    call_2_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[1]["messages"])

    # specialist_alpha1 reviewing specialist_alpha2 sees alpha2's summary
    assert "SHARED_ALPHA_INTERNAL_SUMMARY_TWO" in call_1_text
    # specialist_alpha2 reviewing specialist_alpha1 sees alpha1's summary
    assert "SHARED_ALPHA_INTERNAL_SUMMARY_ONE" in call_2_text


@pytest.mark.asyncio
async def test_doc_critique_batched_sanitizes_cross_domain_prompts():
    """Verify run_peer_critiques in batched mode withholds summaries for cross-domain panels."""
    mock_model = MockChatModel(model_name="mock-doc-critique-batched")

    mock_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid cross-domain parameters.",
            "proposed_resolution": "Adopt.",
        },
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_alpha",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid cross-domain configuration.",
            "proposed_resolution": "Adopt.",
        },
    ])

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.ops",
        summary="ALPHA_CLASSIFIED_BATCH_SUMMARY",
        exported_claims=[
            TypedClaim(kind="quantity", key="qps", value=200.0, unit="rate", source_scope="domain_alpha.ops")
        ],
        staged_actions=[],
    )
    prop_beta = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="domain_beta.ops",
        summary="BETA_CLASSIFIED_BATCH_SUMMARY",
        exported_claims=[],
        staged_actions=[],
    )

    critiques = await run_peer_critiques(
        proposals=[prop_alpha, prop_beta],
        mode="batched",
        model=mock_model,
        round_num=1,
    )

    assert len(critiques) == 2
    assert len(mock_model.calls) == 1

    prompt_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    assert "[Summary withheld across domain boundaries]" in prompt_text
    assert "ALPHA_CLASSIFIED_BATCH_SUMMARY" not in prompt_text
    assert "BETA_CLASSIFIED_BATCH_SUMMARY" not in prompt_text


# ============================================================================
# 7. Scope Context Isolation in Proposal & Revision
# ============================================================================

@pytest.mark.asyncio
async def test_scope_context_bound_in_propose_and_revise():
    """Verify propose.py and revise.py bind ScopeContext to the active agent's scope."""
    tracking_model = ScopeTrackingChatModel(model_name="mock-scope-tracker")

    # Queue valid proposal JSON
    tracking_model.queue_response({
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.tasks",
        "summary": "Alpha initial proposal.",
        "recommendations": ["Step 1"],
        "resource_claims": {},
    })

    prop = await generate_agent_proposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.tasks",
        model=tracking_model,
    )

    assert prop.agent_id == "specialist_alpha"
    assert "domain_alpha.tasks" in tracking_model.observed_scopes

    # Test revision phase with a different scope
    tracking_model.queue_response({
        "agent_id": "specialist_beta",
        "round_num": 2,
        "scope": "domain_beta.tasks",
        "summary": "Beta revised proposal.",
        "recommendations": ["Revised step"],
        "resource_claims": {},
    })

    prior_prop_beta = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="domain_beta.tasks",
        summary="Beta original proposal.",
        resource_claims={},
        staged_actions=[],
    )
    blocking_critique = PeerCritique(
        reviewer_agent_id="specialist_alpha",
        target_agent_id="specialist_beta",
        round_num=1,
        stance="amend",
        issue_type="resource_overbudget",
        critique="Needs lower allocation.",
        proposed_resolution="Scale down to 5.",
    )

    revised_props = await run_selective_revision(
        active_proposals={"specialist_beta": prior_prop_beta},
        critiques=[blocking_critique],
        round_num=2,
        model=tracking_model,
    )

    assert "specialist_beta" in revised_props
    assert "domain_beta.tasks" in tracking_model.observed_scopes


# ============================================================================
# 8. Blackboard State Serialization Roundtrip with Recorded Cross Reads
# ============================================================================

def test_blackboard_state_dict_roundtrip_with_cross_reads():
    """Verify BlackboardManager to_state_dict and from_state_dict serialize recorded_cross_reads."""
    bb = BlackboardManager(panel_id="panel_serialize_test")
    bb.recorded_cross_reads.append({
        "reader_agent_id": "specialist_beta",
        "reader_scope": "domain_beta.tasks",
        "target_agent_id": "specialist_alpha",
        "target_scope": "domain_alpha.tasks",
        "claim_keys": ["quota_limit"],
        "round_num": 1,
    })

    state_dict = bb.to_state_dict()
    assert len(state_dict["recorded_cross_reads"]) == 1

    restored = BlackboardManager.from_state_dict(state_dict)
    assert restored.panel_id == "panel_serialize_test"
    assert len(restored.recorded_cross_reads) == 1
    assert restored.recorded_cross_reads[0]["claim_keys"] == ["quota_limit"]


# ============================================================================
# 9. Milestone 3 Iteration 2 Remediation Tests
# ============================================================================

def test_filter_scoped_proposals_fails_closed_on_empty_reader_scope():
    """Verify that empty or None reader_scope fails closed into cross-domain filtering (ADR 0001 §2.3)."""
    bb = BlackboardManager(panel_id="panel_empty_scope_fail_closed")

    claim_metric = TypedClaim(
        kind="quantity",
        key="quota_limit",
        value=50.0,
        unit="units",
        source_scope="domain_alpha.tasks",
    )
    prop = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.tasks",
        summary="Confidential Alpha internal plan.",
        recommendations=["Internal recommendation alpha"],
        resource_claims={"rate_limit": 10.0},
        exported_claims=[claim_metric],
        staged_actions=[],
    )
    bb.record_proposal(prop)

    # 1. Test empty string reader_scope
    scoped_views_empty, _ = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope="",
        declared_reads=[],
        granted_scopes=[],
    )
    assert "specialist_alpha" in scoped_views_empty
    view_empty = scoped_views_empty["specialist_alpha"]
    assert view_empty.summary == ""
    assert view_empty.recommendations == []
    assert view_empty.staged_actions == []
    assert view_empty.resource_claims == {}

    # 2. Test None reader_scope
    scoped_views_none, _ = bb.filter_scoped_proposals(
        reader_agent_id="specialist_beta",
        reader_scope=None,
        declared_reads=[],
        granted_scopes=[],
    )
    assert "specialist_alpha" in scoped_views_none
    view_none = scoped_views_none["specialist_alpha"]
    assert view_none.summary == ""
    assert view_none.recommendations == []
    assert view_none.staged_actions == []
    assert view_none.resource_claims == {}


def test_filter_scoped_proposals_rejects_spoofed_claim_source_scope():
    """Verify that a claim with a spoofed or mismatched source_scope is withheld and emitted as an undisclosed constraint."""
    bb = BlackboardManager(panel_id="panel_spoofed_claim")

    # Proposer is in domain_alpha, but attempts to export a claim attributed to foreign domain_beta
    spoofed_claim = TypedClaim(
        kind="quantity",
        key="forged_quota",
        value=999.0,
        unit="units",
        source_scope="domain_beta.network",
    )
    legit_claim = TypedClaim(
        kind="quantity",
        key="valid_quota",
        value=20.0,
        unit="units",
        source_scope="domain_alpha.network",
    )

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.network",
        summary="Alpha configuration.",
        exported_claims=[spoofed_claim, legit_claim],
        staged_actions=[],
    )
    bb.record_proposal(prop_alpha)

    # Reader specialist_gamma holds grants for both domain_alpha and domain_beta
    scoped_views, cross_read_events = bb.filter_scoped_proposals(
        reader_agent_id="specialist_gamma",
        reader_scope="domain_gamma.service",
        declared_reads=["domain_alpha.*", "domain_beta.*"],
        granted_scopes=["domain_alpha.*", "domain_beta.*"],
        round_num=1,
    )

    view_alpha = scoped_views["specialist_alpha"]
    assert view_alpha.summary == ""
    # Spoofed claim must NOT be in exported_claims
    claim_keys = [c.key for c in view_alpha.exported_claims]
    assert "valid_quota" in claim_keys
    assert "forged_quota" not in claim_keys
    # Withheld count > 0 causes undisclosed_constraint to be emitted
    assert "undisclosed_constraint" in claim_keys

    # Audit event should only record valid_quota
    assert len(cross_read_events) == 1
    assert cross_read_events[0]["claim_keys"] == ["valid_quota"]


@pytest.mark.asyncio
async def test_doc_critique_batched_withholds_summary_on_mixed_unscoped_panel():
    """Verify that batched critique treats mixed or unscoped panels as cross-domain and withholds summaries."""
    mock_model = MockChatModel(model_name="mock-doc-critique-batched-mixed")
    mock_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid supporting points for cross-scope constraints.",
            "proposed_resolution": "Commit",
        }
    ])

    claim_metric = TypedClaim(
        kind="quantity",
        key="throughput_limit",
        value=42.0,
        unit="rate",
        source_scope="domain_alpha.ops",
    )
    proposals = [
        AgentProposal(
            agent_id="specialist_alpha",
            round_num=1,
            scope="domain_alpha.ops",
            summary="Confidential Alpha operations roadmap.",
            exported_claims=[claim_metric],
            staged_actions=[],
        ),
        AgentProposal(
            agent_id="specialist_beta",
            round_num=1,
            scope="",  # Unscoped / empty scope proposal
            summary="Beta unclassified operations overview.",
            exported_claims=[],
            staged_actions=[],
        ),
    ]

    critiques = await run_peer_critiques(
        proposals=proposals,
        mode="batched",
        model=mock_model,
        round_num=1,
    )

    assert len(critiques) == 1
    assert mock_model.call_count == 1

    # Verify that the prompt sent to the model withheld the confidential summary
    prompt_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    assert "Confidential Alpha operations roadmap." not in prompt_text
    assert "[Summary withheld across domain boundaries]" in prompt_text
    assert "throughput_limit" in prompt_text


@pytest.mark.asyncio
async def test_doc_critique_batched_withholds_summary_on_all_unscoped_proposals():
    """Verify that batched critique with all unscoped proposals fails closed and withholds summaries."""
    mock_model = MockChatModel(model_name="mock-doc-critique-batched-all-unscoped")
    mock_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid supporting points for cross-scope constraints.",
            "proposed_resolution": "Commit",
        }
    ])

    proposals = [
        AgentProposal(
            agent_id="specialist_alpha",
            round_num=1,
            scope="",
            summary="ALPHA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
        AgentProposal(
            agent_id="specialist_beta",
            round_num=1,
            scope="",
            summary="BETA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
    ]

    critiques = await run_peer_critiques(
        proposals=proposals,
        mode="batched",
        model=mock_model,
        round_num=1,
    )

    assert len(critiques) == 1
    assert mock_model.call_count == 1
    prompt_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    assert "ALPHA_SECRET_PLAN" not in prompt_text
    assert "BETA_SECRET_PLAN" not in prompt_text
    assert "[Summary withheld across domain boundaries]" in prompt_text


@pytest.mark.asyncio
async def test_doc_critique_batched_withholds_summary_on_whitespace_scopes():
    """Verify that batched critique with whitespace scopes fails closed and withholds summaries."""
    mock_model = MockChatModel(model_name="mock-doc-critique-batched-whitespace")
    mock_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid supporting points for cross-scope constraints.",
            "proposed_resolution": "Commit",
        }
    ])

    proposals = [
        AgentProposal(
            agent_id="specialist_alpha",
            round_num=1,
            scope="   ",
            summary="ALPHA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
        AgentProposal(
            agent_id="specialist_beta",
            round_num=1,
            scope=" \t ",
            summary="BETA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
    ]

    critiques = await run_peer_critiques(
        proposals=proposals,
        mode="batched",
        model=mock_model,
        round_num=1,
    )

    assert len(critiques) == 1
    assert mock_model.call_count == 1
    prompt_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    assert "ALPHA_SECRET_PLAN" not in prompt_text
    assert "BETA_SECRET_PLAN" not in prompt_text
    assert "[Summary withheld across domain boundaries]" in prompt_text


@pytest.mark.asyncio
async def test_doc_critique_batched_withholds_summary_on_path_traversal_scopes():
    """Verify that batched critique with path traversal scopes fails closed and withholds summaries."""
    mock_model = MockChatModel(model_name="mock-doc-critique-batched-traversal")
    mock_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Valid supporting points for cross-scope constraints.",
            "proposed_resolution": "Commit",
        }
    ])

    proposals = [
        AgentProposal(
            agent_id="specialist_alpha",
            round_num=1,
            scope="../domain_a",
            summary="ALPHA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
        AgentProposal(
            agent_id="specialist_beta",
            round_num=1,
            scope="../domain_b",
            summary="BETA_SECRET_PLAN",
            exported_claims=[],
            staged_actions=[],
        ),
    ]

    critiques = await run_peer_critiques(
        proposals=proposals,
        mode="batched",
        model=mock_model,
        round_num=1,
    )

    assert len(critiques) == 1
    assert mock_model.call_count == 1
    prompt_text = " ".join(getattr(m, "content", "") for m in mock_model.calls[0]["messages"])
    assert "ALPHA_SECRET_PLAN" not in prompt_text
    assert "BETA_SECRET_PLAN" not in prompt_text
    assert "[Summary withheld across domain boundaries]" in prompt_text


@pytest.mark.asyncio
async def test_doc_critique_per_agent_binds_reviewer_scope_context():
    """Verify that run_peer_critiques in per_agent mode binds each reviewer's own scope in ScopeContext during critique invocation."""
    tracking_model = ScopeTrackingChatModel(model_name="tracking-critique-model")

    # Queue response for reviewer alpha reviewing beta
    tracking_model.queue_response([
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "amend",
            "issue_type": "resource_overbudget",
            "critique": "Request resource reduction.",
            "proposed_resolution": "Lower quota.",
        }
    ])
    # Queue response for reviewer beta reviewing alpha
    tracking_model.queue_response([
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_alpha",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Agree with architectural synergy.",
            "proposed_resolution": "Commit",
        }
    ])

    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="domain_alpha.tasks",
        summary="Alpha summary.",
        exported_claims=[],
        staged_actions=[],
    )
    prop_beta = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="domain_beta.reports",
        summary="Beta summary.",
        exported_claims=[],
        staged_actions=[],
    )

    critiques = await run_peer_critiques(
        proposals=[prop_alpha, prop_beta],
        mode="per_agent",
        model=tracking_model,
        round_num=1,
    )

    assert len(critiques) == 2
    assert tracking_model.call_count == 2
    # Verify observed scopes during model execution
    assert "domain_alpha.tasks" in tracking_model.observed_scopes
    assert "domain_beta.reports" in tracking_model.observed_scopes


@pytest.mark.asyncio
async def test_deliberation_engine_run_emits_cross_read_audit_to_db_hash_chain(
    async_db_session: AsyncSession,
) -> None:
    """Verify that DeliberationEngine.run executes cross-read audit logging to DB hash chain and state channels."""
    profile_id = "profile_delib_engine_cross_audit"
    panel_id = "panel_delib_engine_cross_audit"

    mock_model = MockChatModel(model_name="mock-delib-cross-audit")

    # Round 1: Specialist Alpha proposal (with exported claim)
    prop_alpha_data = {
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.services",
        "summary": "Alpha infrastructure plan.",
        "recommendations": ["Recommendation Alpha"],
        "resource_claims": {},
        "exported_claims": [
            {
                "kind": "quantity",
                "key": "latency_threshold",
                "value": 25.0,
                "unit": "seconds",
                "source_scope": "domain_alpha.services",
            }
        ],
    }

    # Round 1: Specialist Beta proposal
    prop_beta_data = {
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "domain_beta.auditor",
        "summary": "Beta monitoring plan.",
        "recommendations": ["Recommendation Beta"],
        "resource_claims": {},
        "exported_claims": [],
    }

    # Peer critique: Alpha reviews Beta
    critique_alpha_to_beta = [
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Endorse Beta monitoring specifications.",
            "proposed_resolution": "Commit",
        }
    ]

    # Peer critique: Beta reviews Alpha
    critique_beta_to_alpha = [
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_alpha",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Endorse Alpha latency constraints.",
            "proposed_resolution": "Commit",
        }
    ]

    mock_model.queue_response(prop_alpha_data)
    mock_model.queue_response(prop_beta_data)
    mock_model.queue_response(critique_alpha_to_beta)
    mock_model.queue_response(critique_beta_to_alpha)

    delib_config = DeliberationConfig(
        panel_id=panel_id,
        critique_mode="per_agent",
    )

    engine = DeliberationEngine(
        model=mock_model,
        config=delib_config,
        session=async_db_session,
    )

    state = create_initial_state(
        prompt="Coordinate multi-agent cross-domain infrastructure",
        target_agents=["specialist_alpha", "specialist_beta"],
        user_id="user_admin",
    )
    state["profile_id"] = profile_id
    state["agent_scopes"] = {
        "specialist_alpha": "domain_alpha.services",
        "specialist_beta": "domain_beta.auditor",
    }
    state["agent_declared_reads"] = {
        "specialist_beta": ["domain_alpha.*"],
    }
    state["agent_granted_scopes"] = {
        "specialist_beta": ["domain_alpha.*"],
    }

    final_state = await engine.run(state)
    await async_db_session.commit()

    # Query DB to verify the audit event was recorded and chained
    stmt = (
        select(AuditEventRecord)
        .where(AuditEventRecord.profile_id == profile_id)
        .order_by(AuditEventRecord.ts.asc())
        .execution_options(include_all_scopes=True)
    )
    result = await async_db_session.execute(stmt)
    records = result.scalars().all()

    cross_read_records = [r for r in records if r.event == "scope.cross_read"]
    assert len(cross_read_records) == 1
    cr_rec = cross_read_records[0]
    assert cr_rec.scope == "domain_beta.auditor"
    assert cr_rec.prev_hash is not None
    assert len(cr_rec.entry_hash) == 64

    # Verify detail_redacted contents
    detail = json.loads(cr_rec.detail_redacted)
    assert detail["reader_agent_id"] == "specialist_beta"
    assert detail["target_agent_id"] == "specialist_alpha"
    assert "latency_threshold" in detail["claim_keys"]
    assert detail["panel_id"] == panel_id

    # Verify hash chain validity
    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] >= 1

    # Verify state channels forwarded cross-read records
    audit_events = final_state.get("audit_events", [])
    assert any(ev.get("event") == "scope.cross_read" for ev in audit_events)

    delib_state = final_state.get("deliberation_state", {})
    recorded = delib_state.get("recorded_cross_reads", [])
    assert len(recorded) >= 1
    assert recorded[0]["reader_agent_id"] == "specialist_beta"
    assert "latency_threshold" in recorded[0]["claim_keys"]


# ============================================================================
# 8. Empirical Adversarial Stress & Tamper Injection Suite
# ============================================================================

@pytest.mark.asyncio
async def test_adversarial_live_deliberation_multi_round_audit_and_tamper_injection(
    async_db_session: AsyncSession,
) -> None:
    """Empirical Adversarial Test: Multi-agent, multi-round deliberation with cross-domain agents,

    verifying live DB audit chain persistence and raw SQL tamper injection detection.
    """
    profile_id = "profile_adv_delib_multi_round_tamper"
    panel_id = "panel_adv_delib_multi_round_tamper"

    mock_model = MockChatModel(model_name="mock-adv-delib-multi-round")

    # Round 1: Specialist Alpha (Storage) exports latency_threshold (50.0s)
    prop_alpha_r1 = {
        "agent_id": "specialist_alpha",
        "round_num": 1,
        "scope": "domain_alpha.storage",
        "summary": "Storage tier configuration.",
        "recommendations": ["Deploy storage tier"],
        "resource_claims": {},
        "exported_claims": [
            {
                "kind": "quantity",
                "key": "latency_threshold",
                "value": 50.0,
                "unit": "seconds",
                "source_scope": "domain_alpha.storage",
            }
        ],
    }

    # Round 1: Specialist Beta (Network) exports throughput_rate (100.0)
    prop_beta_r1 = {
        "agent_id": "specialist_beta",
        "round_num": 1,
        "scope": "domain_beta.network",
        "summary": "Network backbone configuration.",
        "recommendations": ["Route backbone traffic"],
        "resource_claims": {},
        "exported_claims": [
            {
                "kind": "quantity",
                "key": "throughput_rate",
                "value": 100.0,
                "unit": "rate",
                "source_scope": "domain_beta.network",
            }
        ],
    }

    # Round 1: Specialist Gamma (Compute) exports compute_limit (4.0)
    prop_gamma_r1 = {
        "agent_id": "specialist_gamma",
        "round_num": 1,
        "scope": "domain_gamma.compute",
        "summary": "Compute node scaling configuration.",
        "recommendations": ["Scale compute instances"],
        "resource_claims": {},
        "exported_claims": [
            {
                "kind": "quantity",
                "key": "compute_limit",
                "value": 4.0,
                "unit": "units",
                "source_scope": "domain_gamma.compute",
            }
        ],
    }

    # Round 1 Peer Critiques:
    # Alpha reviews Beta & Gamma (Endorse)
    critique_alpha_r1 = [
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Network throughput aligns with storage transfer.",
            "proposed_resolution": "Commit",
        },
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_gamma",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Compute capacity aligns with storage volume.",
            "proposed_resolution": "Commit",
        },
    ]

    # Beta reviews Alpha (CONFLICT on latency: 50s is too high, must be <= 10s) and Gamma (Endorse)
    critique_beta_r1 = [
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_alpha",
            "round_num": 1,
            "stance": "conflict",
            "issue_type": "resource_overbudget",
            "critique": "Latency 50.0s is excessive for network backbone; must be <= 10.0s.",
            "proposed_resolution": "Reduce latency_threshold to 10.0s.",
        },
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_gamma",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Compute sizing compatible with network buffers.",
            "proposed_resolution": "Commit",
        },
    ]

    # Gamma reviews Alpha & Beta: Endorse
    critique_gamma_r1 = [
        {
            "reviewer_agent_id": "specialist_gamma",
            "target_agent_id": "specialist_alpha",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Storage profile compatible with compute nodes.",
            "proposed_resolution": "Commit",
        },
        {
            "reviewer_agent_id": "specialist_gamma",
            "target_agent_id": "specialist_beta",
            "round_num": 1,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Network throughput aligns with compute ingest.",
            "proposed_resolution": "Commit",
        },
    ]

    # Round 2: Alpha selectively revises its proposal to address Beta's CONFLICT
    prop_alpha_r2 = {
        "agent_id": "specialist_alpha",
        "round_num": 2,
        "scope": "domain_alpha.storage",
        "summary": "Revised storage tier with reduced latency.",
        "recommendations": ["Deploy optimized storage tier"],
        "resource_claims": {},
        "exported_claims": [
            {
                "kind": "quantity",
                "key": "latency_threshold",
                "value": 10.0,
                "unit": "seconds",
                "source_scope": "domain_alpha.storage",
            }
        ],
    }

    # Round 2 Peer Critiques:
    critique_alpha_r2 = [
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_beta",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Network throughput aligns with storage transfer.",
            "proposed_resolution": "Commit",
        },
        {
            "reviewer_agent_id": "specialist_alpha",
            "target_agent_id": "specialist_gamma",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Compute capacity aligns with storage volume.",
            "proposed_resolution": "Commit",
        },
    ]

    # Beta reviews Alpha: ENDORSE now that latency is 10.0s
    critique_beta_r2 = [
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_alpha",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Latency 10.0s is fully compliant with network backbone.",
            "proposed_resolution": "Commit",
        },
        {
            "reviewer_agent_id": "specialist_beta",
            "target_agent_id": "specialist_gamma",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Compute sizing compatible with network buffers.",
            "proposed_resolution": "Commit",
        },
    ]

    critique_gamma_r2 = [
        {
            "reviewer_agent_id": "specialist_gamma",
            "target_agent_id": "specialist_alpha",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Storage profile compatible with compute nodes.",
            "proposed_resolution": "Commit",
        },
        {
            "reviewer_agent_id": "specialist_gamma",
            "target_agent_id": "specialist_beta",
            "round_num": 2,
            "stance": "endorse",
            "issue_type": "synergy",
            "critique": "Network throughput aligns with compute ingest.",
            "proposed_resolution": "Commit",
        },
    ]

    # Queue responses in order of execution:
    # Round 1: Alpha, Beta, Gamma initial proposals
    mock_model.queue_response(prop_alpha_r1)
    mock_model.queue_response(prop_beta_r1)
    mock_model.queue_response(prop_gamma_r1)

    # Round 1 Peer reviews:
    # Alpha reviews peers, Beta reviews peers, Gamma reviews peers
    mock_model.queue_response(critique_alpha_r1)
    mock_model.queue_response(critique_beta_r1)
    mock_model.queue_response(critique_gamma_r1)

    # Round 2 SelectiveRevise: Alpha revised proposal
    mock_model.queue_response(prop_alpha_r2)

    # Round 2 Peer reviews:
    mock_model.queue_response(critique_alpha_r2)
    mock_model.queue_response(critique_beta_r2)
    mock_model.queue_response(critique_gamma_r2)

    delib_config = DeliberationConfig(
        panel_id=panel_id,
        critique_mode="per_agent",
        budget=DeliberationBudget(max_rounds=3),
    )

    engine = DeliberationEngine(
        model=mock_model,
        config=delib_config,
        session=async_db_session,
    )

    state = create_initial_state(
        prompt="Coordinate multi-tier infrastructure",
        target_agents=["specialist_alpha", "specialist_beta", "specialist_gamma"],
        user_id="user_admin",
    )
    state["profile_id"] = profile_id
    state["agent_scopes"] = {
        "specialist_alpha": "domain_alpha.storage",
        "specialist_beta": "domain_beta.network",
        "specialist_gamma": "domain_gamma.compute",
    }
    state["agent_declared_reads"] = {
        "specialist_alpha": ["domain_gamma.*"],
        "specialist_beta": ["domain_alpha.*"],
        "specialist_gamma": ["domain_alpha.*", "domain_beta.*"],
    }
    state["agent_granted_scopes"] = {
        "specialist_alpha": ["domain_gamma.*"],
        "specialist_beta": ["domain_alpha.*"],
        "specialist_gamma": ["domain_alpha.*", "domain_beta.*"],
    }

    final_state = await engine.run(state)
    await async_db_session.commit()

    # Step 1: Verify Deliberation converged after 2 rounds
    delib_state = final_state.get("deliberation_state", {})
    assert delib_state.get("rounds_used") == 2
    assert delib_state.get("converged") is True

    # Step 2: Query DB for audit event records
    stmt = (
        select(AuditEventRecord)
        .where(AuditEventRecord.profile_id == profile_id)
        .order_by(AuditEventRecord.ts.asc(), AuditEventRecord.id.asc())
        .execution_options(include_all_scopes=True)
    )
    result = await async_db_session.execute(stmt)
    records = list(result.scalars().all())

    # We expect multiple scope.cross_read events recorded in the live DB across round 1 and round 2
    cross_read_records = [r for r in records if r.event == "scope.cross_read"]
    assert len(cross_read_records) >= 3

    # Check structure of cross_read events
    for cr in cross_read_records:
        assert cr.scope in ("domain_alpha.storage", "domain_beta.network", "domain_gamma.compute")
        assert len(cr.entry_hash) == 64
        assert cr.prev_hash is not None
        payload_data = json.loads(cr.detail_redacted)
        assert "reader_agent_id" in payload_data
        assert "target_agent_id" in payload_data
        assert "claim_keys" in payload_data
        assert payload_data["panel_id"] == panel_id

    # Step 3: Verify the entire cryptographic hash chain is valid from GENESIS to tail
    initial_verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert initial_verification["valid"] is True
    assert initial_verification["checked_count"] == len(records)
    assert initial_verification["head_hash"] == records[-1].entry_hash
    assert initial_verification["broken_at_event_id"] is None
    assert initial_verification["reason"] is None

    # ========================================================================
    # Step 4: Adversarial Tamper Injection 1 — payload_hash corruption
    # ========================================================================
    target_rec = cross_read_records[1]
    orig_payload_hash = target_rec.payload_hash

    corrupted_payload = "corrupted_payload_hash_deadbeef00112233445566778899aabbccddeeff"
    await async_db_session.execute(
        text("UPDATE audit_events SET payload_hash = :corrupted WHERE id = :event_id"),
        {"corrupted": corrupted_payload, "event_id": target_rec.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    tamper_result_1 = await verify_profile_audit_chain(async_db_session, profile_id)
    assert tamper_result_1["valid"] is False
    assert tamper_result_1["reason"] == "hash_mismatch"
    assert tamper_result_1["broken_at_event_id"] == target_rec.id

    # Revert Tamper 1
    await async_db_session.execute(
        text("UPDATE audit_events SET payload_hash = :orig WHERE id = :event_id"),
        {"orig": orig_payload_hash, "event_id": target_rec.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # Confirm restored integrity
    reverted_verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert reverted_verif["valid"] is True

    # ========================================================================
    # Step 5: Adversarial Tamper Injection 2 — prev_hash corruption
    # ========================================================================
    orig_prev_hash = target_rec.prev_hash
    corrupted_prev = "corrupted_prev_hash_11223344556677889900aabbccddeeff00112233"
    await async_db_session.execute(
        text("UPDATE audit_events SET prev_hash = :corrupted WHERE id = :event_id"),
        {"corrupted": corrupted_prev, "event_id": target_rec.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    tamper_result_2 = await verify_profile_audit_chain(async_db_session, profile_id)
    assert tamper_result_2["valid"] is False
    assert tamper_result_2["reason"] == "prev_hash_mismatch"
    assert tamper_result_2["broken_at_event_id"] == target_rec.id

    # Revert Tamper 2
    await async_db_session.execute(
        text("UPDATE audit_events SET prev_hash = :orig WHERE id = :event_id"),
        {"orig": orig_prev_hash, "event_id": target_rec.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    assert (await verify_profile_audit_chain(async_db_session, profile_id))["valid"] is True

    # ========================================================================
    # Step 6: Adversarial Tamper Injection 3 — Row Deletion
    # ========================================================================
    # Identify the subsequent record in the chain
    rec_index = [r.id for r in records].index(target_rec.id)
    subsequent_rec_id = records[rec_index + 1].id

    await async_db_session.execute(
        text("DELETE FROM audit_events WHERE id = :event_id"),
        {"event_id": target_rec.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # The chain must detect the break at subsequent_rec_id because its prev_hash
    # points to the deleted record, not the one before it!
    tamper_result_3 = await verify_profile_audit_chain(async_db_session, profile_id)
    assert tamper_result_3["valid"] is False
    assert tamper_result_3["reason"] == "prev_hash_mismatch"
    assert tamper_result_3["broken_at_event_id"] == subsequent_rec_id


@pytest.mark.asyncio
async def test_adversarial_cross_domain_audit_concurrency_and_interleaving(
    async_db_session: AsyncSession,
) -> None:
    """Empirical Stress Test: Interleaved and sequential cross-reads and tool events

    under multiple rounds, ensuring strict cryptographic chain integrity and monotonic ordering.
    """
    from yarvelle_core.audit.hash_chain import append_chained_audit_event, record_scope_cross_read_audit

    profile_id = "profile_adv_stress_interleaving_matrix"

    # Seed with genesis run event
    base = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_system.runtime",
        pack_id="domain_system",
    )

    interleaved_plan = [
        ("cross_read", "specialist_beta", "domain_beta.ops", "specialist_alpha", "domain_alpha.ops", ["quota_claim"], 1),
        ("tool", "tool_read_metrics", "domain_beta.ops"),
        ("cross_read", "specialist_gamma", "domain_gamma.ops", "specialist_beta", "domain_beta.ops", ["bandwidth_claim"], 1),
        ("tool", "tool_query_storage", "domain_gamma.ops"),
        ("cross_read", "specialist_alpha", "domain_alpha.ops", "specialist_gamma", "domain_gamma.ops", ["cpu_claim"], 1),
        ("run", None, "domain_system.runtime"),
        ("cross_read", "specialist_beta", "domain_beta.ops", "specialist_alpha", "domain_alpha.ops", ["revised_quota_claim"], 2),
        ("tool", "tool_verify_state", "domain_beta.ops"),
        ("cross_read", "specialist_gamma", "domain_gamma.ops", "specialist_alpha", "domain_alpha.ops", ["revised_quota_claim"], 2),
    ]

    records = [base]
    for step in interleaved_plan:
        kind = step[0]
        if kind == "cross_read":
            _, r_id, r_sc, t_id, t_sc, keys, rnd = step
            rec = await record_scope_cross_read_audit(
                async_db_session,
                reader_agent_id=r_id,
                reader_scope=r_sc,
                target_agent_id=t_id,
                target_scope=t_sc,
                claim_keys=keys,
                round_num=rnd,
                profile_id=profile_id,
            )
        elif kind == "tool":
            _, t_name, sc = step
            rec = await append_chained_audit_event(
                async_db_session,
                profile_id=profile_id,
                event="tool",
                tool=t_name,
                scope=sc,
                risk="read",
                decision="allow",
            )
        else:
            _, _, sc = step
            rec = await append_chained_audit_event(
                async_db_session,
                profile_id=profile_id,
                event="run",
                scope=sc,
            )
        records.append(rec)

    await async_db_session.commit()

    # Verify cryptographic chaining across all records
    for idx in range(1, len(records)):
        assert records[idx].prev_hash == records[idx - 1].entry_hash
        assert records[idx].ts >= records[idx - 1].ts

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == len(records)
    assert verification["head_hash"] == records[-1].entry_hash
    assert verification["broken_at_event_id"] is None


