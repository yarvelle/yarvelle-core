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

"""Unit and integration test suite for Milestone 4 (Phase 3 Staged Actions).

Covers ADR 0001 §2.6, §2.11 item 6, §7 Phase 3:
1. Deterministic tool risk tier derivation (fail-closed, never trusting model).
2. Proposal & revision staged action collection and parameter binding.
3. Blackboard active staged actions aggregation and serialization.
4. Universal forced human approval across risk tiers and autonomy levels (A0-A3).
5. Single-use cryptographic action binding (agent_id, profile_id, tool_name, payload hash).
6. ResponseSynthesizer staged action card rendering and tool_calls packaging.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yarvelle_core.api.approvals import consume_approval_atomic
from yarvelle_core.db.models import Approval, Base
from yarvelle_core.engine.tool_exec import (
    PolicyDecision,
    SqlApprovalStore,
    ToolContext,
    ToolSpec,
    compute_action_binding_hash,
    compute_payload_hash,
    evaluate_policy_gate,
    execute_tool_call,
)
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.deliberation.tool_gate import (
    derive_tool_risk_tier,
    evaluate_deliberation_tool_gate,
    filter_read_only_tools,
)
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.state import AgentProposal, CritiqueStance, PeerCritique, StagedAction


class MockChatModel:
    """Mock language model returning pre-scripted responses."""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self.responses = list(responses or [])
        self.call_count = 0
        self.last_messages: Optional[List[Any]] = None

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_messages = list(messages) if isinstance(messages, list) else [messages]
        if self.responses:
            resp_content = self.responses.pop(0)
        else:
            resp_content = "{}"
        return AIMessage(content=resp_content)

    def bind_tools(self, tools: Sequence[Any]) -> MockChatModel:
        return self


# ============================================================================
# 1. Deterministic Tier Derivation (Fail-Closed, Never Trust Model)
# ============================================================================


def test_derive_tool_risk_tier_builtins():
    """Verify derive_tool_risk_tier maps built-in tools correctly."""
    assert derive_tool_risk_tier("attach-read") == "read"
    assert derive_tool_risk_tier("search_records") == "read"
    assert derive_tool_risk_tier("workspace-note") == "write_local"
    assert derive_tool_risk_tier("create_reminder") == "write_local"
    assert derive_tool_risk_tier("calendar_create_event") == "write_external"
    assert derive_tool_risk_tier("gmail_send_message") == "irreversible"


def test_derive_tool_risk_tier_fail_closed_unknown():
    """Verify unknown tools and missing tiers fail closed to 'irreversible'."""
    assert derive_tool_risk_tier("unregistered_mystery_tool") == "irreversible"
    assert derive_tool_risk_tier("") == "irreversible"
    assert derive_tool_risk_tier(None) == "irreversible"  # type: ignore


def test_derive_tool_risk_tier_candidate_tools():
    """Verify candidate tools declared in execution context are honored."""
    custom_spec = ToolSpec(name="fetch_custom_data", risk_tier="read")
    custom_dict = {"name": "save_custom_data", "risk_tier": "write_local"}
    invalid_dict = {"name": "corrupt_data", "risk_tier": "bogus_tier"}

    assert derive_tool_risk_tier("fetch_custom_data", tools=[custom_spec]) == "read"
    assert derive_tool_risk_tier("save_custom_data", tools=[custom_dict]) == "write_local"
    # Unrecognized tier fails closed to irreversible
    assert derive_tool_risk_tier("corrupt_data", tools=[invalid_dict]) == "irreversible"


def test_filter_read_only_tools_with_derivation():
    """Verify filter_read_only_tools resolves tiers and keeps only read-tier tools."""
    tools = [
        ToolSpec(name="attach-read", risk_tier="read"),
        ToolSpec(name="workspace-note", risk_tier="write_local"),
        ToolSpec(name="gmail_send_message", risk_tier="irreversible"),
        {"name": "search_records", "risk_tier": "read"},
        {"name": "unknown_tool"},  # missing tier fails closed
    ]
    filtered = filter_read_only_tools(tools)
    names = [t.name if hasattr(t, "name") else t["name"] for t in filtered]
    assert names == ["attach-read", "search_records"]


# ============================================================================
# 2. Proposal & Revision Staged Action Normalization
# ============================================================================


@pytest.mark.asyncio
async def test_proposal_staged_actions_normalization_and_retention():
    """Verify generate_agent_proposal retains staged actions with deterministic tiers."""
    raw_model_json = json.dumps({
        "agent_id": "spoofed_agent",  # should be bound to specialist
        "round_num": 1,
        "scope": "scope_alpha",
        "summary": "Proposal with staged actions",
        "recommendations": ["Recommendation 1"],
        "resource_claims": {},
        "staged_actions": [
            {
                "tool_name": "workspace-note",
                "tool_args": {"title": "Summary Note", "content": "Deliberation artifact"},
                "rationale": "Record draft notes",
                "risk_tier": "read",  # Attempted forgery: model claims read for a write tool
            },
            {
                "tool_name": "unknown_tool",
                "tool_args": {"cmd": "execute"},
                "rationale": "Unknown operation",
                # missing risk_tier
            },
        ],
    })

    model = MockChatModel([raw_model_json])
    prop = await generate_agent_proposal(
        agent_id="specialist_alpha",
        round_num=1,
        context={"prompt": "Draft task notes"},
        model=model,
        scope="scope_alpha",
    )

    assert prop.agent_id == "specialist_alpha"
    assert len(prop.staged_actions) == 2

    act1 = prop.staged_actions[0]
    assert act1.agent_id == "specialist_alpha"
    assert act1.tool_name == "workspace-note"
    assert act1.risk_tier == "write_local"  # Derived deterministically, forgery overridden!
    assert act1.tool_args == {"title": "Summary Note", "content": "Deliberation artifact"}

    act2 = prop.staged_actions[1]
    assert act2.agent_id == "specialist_alpha"
    assert act2.tool_name == "unknown_tool"
    assert act2.risk_tier == "irreversible"  # Unknown tool fails closed to irreversible!


@pytest.mark.asyncio
async def test_selective_revision_staged_actions_handling():
    """Verify selective revision preserves untargeted staged actions and updates targeted ones."""
    prop_alpha = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="scope_alpha",
        summary="Alpha initial",
        staged_actions=[
            StagedAction(
                agent_id="specialist_alpha",
                tool_name="workspace-note",
                tool_args={"text": "alpha_1"},
                rationale="Initial alpha note",
                risk_tier="write_local",
            )
        ],
    )
    prop_beta = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="scope_beta",
        summary="Beta initial",
        staged_actions=[
            StagedAction(
                agent_id="specialist_beta",
                tool_name="workspace-note",
                tool_args={"text": "beta_1"},
                rationale="Initial beta note",
                risk_tier="write_local",
            )
        ],
    )

    # Beta is targeted by a conflict critique; Alpha is untargeted
    critique_for_beta = PeerCritique(
        reviewer_agent_id="specialist_alpha",
        target_agent_id="specialist_beta",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="dependency_order",
        critique="Beta action must sequence after review",
        proposed_resolution="Revise parameters",
    )

    revised_beta_json = json.dumps({
        "agent_id": "specialist_beta",
        "round_num": 2,
        "scope": "scope_beta",
        "summary": "Beta revised",
        "recommendations": ["Revised recommendation"],
        "resource_claims": {},
        "staged_actions": [
            {
                "tool_name": "workspace-note",
                "tool_args": {"text": "beta_revised_sequenced"},
                "rationale": "Revised sequencing note",
            }
        ],
    })

    model = MockChatModel([revised_beta_json])
    updated = await run_selective_revision(
        active_proposals={"specialist_alpha": prop_alpha, "specialist_beta": prop_beta},
        critiques=[critique_for_beta],
        round_num=2,
        model=model,
    )

    # Specialist Alpha was untargeted: preserved untouched with 0 LLM calls
    assert updated["specialist_alpha"].staged_actions[0].tool_args == {"text": "alpha_1"}
    # Specialist Beta was targeted: updated with revised staged action
    assert updated["specialist_beta"].staged_actions[0].tool_args == {"text": "beta_revised_sequenced"}
    assert updated["specialist_beta"].staged_actions[0].risk_tier == "write_local"


# ============================================================================
# 3. Blackboard Aggregation & Serialization
# ============================================================================


def test_blackboard_get_active_staged_actions():
    """Verify BlackboardManager aggregates staged actions across all active proposals."""
    bb = BlackboardManager(panel_id="test_panel")
    prop1 = AgentProposal(
        agent_id="specialist_alpha",
        round_num=1,
        scope="scope_alpha",
        summary="Proposal 1",
        staged_actions=[
            StagedAction(
                agent_id="specialist_alpha",
                tool_name="workspace-note",
                tool_args={"k": "v1"},
                rationale="Note 1",
                risk_tier="write_local",
            )
        ],
    )
    prop2 = AgentProposal(
        agent_id="specialist_beta",
        round_num=1,
        scope="scope_beta",
        summary="Proposal 2",
        staged_actions=[
            StagedAction(
                agent_id="specialist_beta",
                tool_name="calendar_create_event",
                tool_args={"event": "sync"},
                rationale="Event 2",
                risk_tier="write_external",
            )
        ],
    )

    bb.record_proposal(prop1)
    bb.record_proposal(prop2)

    active_actions = bb.get_active_staged_actions()
    assert len(active_actions) == 2
    tool_names = {a.tool_name for a in active_actions}
    assert tool_names == {"workspace-note", "calendar_create_event"}

    # Verify serialization
    state_dict = bb.to_state_dict()
    assert "staged_actions" in state_dict
    assert len(state_dict["staged_actions"]) == 2

    # Verify hydration
    restored_bb = BlackboardManager.from_state_dict(state_dict)
    restored_actions = restored_bb.get_active_staged_actions()
    assert len(restored_actions) == 2
    assert restored_actions[0].tool_name == "workspace-note"


# ============================================================================
# 4. Universal Forced Human Approval Across All Autonomy Levels (A0-A3)
# ============================================================================


def test_universal_forced_human_approval_panel_staged():
    """Verify ADR 0001 §2.6: Every panel-staged action requires human approval across all autonomy levels."""
    spec_local = ToolSpec(name="workspace-note", risk_tier="write_local")
    spec_ext = ToolSpec(name="calendar_create_event", risk_tier="write_external")
    spec_irrev = ToolSpec(name="gmail_send_message", risk_tier="irreversible")
    args = {"title": "Test", "content": "Body"}

    # Test across all autonomy levels: A0, A1, A2, A3
    for autonomy in ("A0", "A1", "A2", "A3"):
        ctx = ToolContext(
            user_id="user_1",
            profile_id="profile_1",
            autonomy=autonomy,  # type: ignore
            is_panel_staged=True,
        )

        dec_local = evaluate_policy_gate(ctx, spec_local, args, is_panel_staged=True)
        assert dec_local.decision == "needs_approval", f"Failed for {autonomy} on write_local"
        assert dec_local.needs_approval is True

        dec_ext = evaluate_policy_gate(ctx, spec_ext, args, is_panel_staged=True)
        assert dec_ext.decision == "needs_approval", f"Failed for {autonomy} on write_external"
        assert dec_ext.needs_approval is True

        dec_irrev = evaluate_policy_gate(ctx, spec_irrev, args, is_panel_staged=True)
        assert dec_irrev.decision == "needs_approval", f"Failed for {autonomy} on irreversible"
        assert dec_irrev.needs_approval is True


def test_single_agent_policy_gate_preserved():
    """Verify standard single-agent gate behavior is preserved when is_panel_staged is False."""
    spec_local = ToolSpec(name="workspace-note", risk_tier="write_local")
    spec_ext = ToolSpec(name="calendar_create_event", risk_tier="write_external")
    args = {"title": "Test"}

    # A1 allows write_local
    ctx_a1 = ToolContext(user_id="u1", profile_id="p1", autonomy="A1", is_panel_staged=False)
    dec_a1_local = evaluate_policy_gate(ctx_a1, spec_local, args, is_panel_staged=False)
    assert dec_a1_local.decision == "allow"
    assert dec_a1_local.allowed is True

    # A1 requires approval for write_external
    dec_a1_ext = evaluate_policy_gate(ctx_a1, spec_ext, args, is_panel_staged=False)
    assert dec_a1_ext.decision == "needs_approval"

    # A2 allows write_local and consented write_external
    ctx_a2 = ToolContext(user_id="u1", profile_id="p1", autonomy="A2", is_panel_staged=False)
    dec_a2_local = evaluate_policy_gate(ctx_a2, spec_local, args, is_panel_staged=False)
    assert dec_a2_local.decision == "allow"

    dec_a2_ext_consented = evaluate_policy_gate(
        ctx_a2, spec_ext, args, consents={"external_write_consent": True}, is_panel_staged=False
    )
    assert dec_a2_ext_consented.decision == "allow"

    # A3 allows all writes in single-agent execution
    ctx_a3 = ToolContext(user_id="u1", profile_id="p1", autonomy="A3", is_panel_staged=False)
    dec_a3_local = evaluate_policy_gate(ctx_a3, spec_local, args, is_panel_staged=False)
    assert dec_a3_local.decision == "allow"

    dec_a3_ext = evaluate_policy_gate(ctx_a3, spec_ext, args, is_panel_staged=False)
    assert dec_a3_ext.decision == "allow"


def test_child_under_13_precedence_over_panel_approval():
    """Verify Child Under 13 external writes are hard-blocked even when panel-staged."""
    spec_ext = ToolSpec(name="calendar_create_event", risk_tier="write_external")
    ctx_child = ToolContext(
        user_id="child_user",
        profile_id="child_profile",
        autonomy="A1",
        is_panel_staged=True,
        extra={"age_band": "child_under_13"},
    )
    dec = evaluate_policy_gate(ctx_child, spec_ext, {"event": "party"}, is_panel_staged=True)
    assert dec.decision == "blocked"
    assert dec.allowed is False
    assert "child" in dec.reason.lower()


# ============================================================================
# 5. Single-Use Cryptographic Parameter Binding (AU-18)
# ============================================================================


@pytest.mark.asyncio
async def test_single_use_cryptographic_binding_atomic():
    """Verify single-use token consumption binding agent_id, tool_name, profile_id, and payload hash."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tool_args = {"doc_id": "doc-100", "operation": "stage"}
    payload_h = compute_payload_hash(tool_args)
    action_binding_h = compute_action_binding_hash("specialist_alpha", "store_record", tool_args)
    assert len(action_binding_h) == 64

    # 1. Create approval in DB
    now = datetime.now(timezone.utc)
    app_id = "app_test_atomic_1"
    async with session_factory() as session:
        app = Approval(
            id=app_id,
            profile_id="profile_main",
            run_id="run_1",
            agent_id="specialist_alpha",
            tool_name="store_record",
            args_redacted=json.dumps(tool_args),
            payload_hash=payload_h,
            risk_tier="write_local",
            status="approved",
            expires_at=now + timedelta(minutes=15),
            created_at=now,
        )
        session.add(app)
        await session.commit()

    # 2. Consumption with identical parameters succeeds
    async with session_factory() as session:
        consumed_id = await consume_approval_atomic(
            session,
            app_id,
            tool_args,
            profile_id="profile_main",
            tool_name="store_record",
            agent_id="specialist_alpha",
        )
        assert consumed_id == app_id

    # 3. Second consumption attempt fails (single-use token invariant)
    async with session_factory() as session:
        with pytest.raises(ValueError, match="cannot consume|already been consumed"):
            await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="profile_main",
                tool_name="store_record",
                agent_id="specialist_alpha",
            )

    # 4. Agent mismatch fails closed
    app_id_2 = "app_test_atomic_2"
    async with session_factory() as session:
        app2 = Approval(
            id=app_id_2,
            profile_id="profile_main",
            run_id="run_1",
            agent_id="specialist_alpha",
            tool_name="store_record",
            args_redacted=json.dumps(tool_args),
            payload_hash=payload_h,
            risk_tier="write_local",
            status="approved",
            expires_at=now + timedelta(minutes=15),
            created_at=now,
        )
        session.add(app2)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="different agent"):
            await consume_approval_atomic(
                session,
                app_id_2,
                tool_args,
                profile_id="profile_main",
                tool_name="store_record",
                agent_id="specialist_intruder",  # Spoofed agent
            )

    # 5. Modified arguments fail closed with payload hash mismatch
    app_id_3 = "app_test_atomic_3"
    async with session_factory() as session:
        app3 = Approval(
            id=app_id_3,
            profile_id="profile_main",
            run_id="run_1",
            agent_id="specialist_alpha",
            tool_name="store_record",
            args_redacted=json.dumps(tool_args),
            payload_hash=payload_h,
            risk_tier="write_local",
            status="approved",
            expires_at=now + timedelta(minutes=15),
            created_at=now,
        )
        session.add(app3)
        await session.commit()

    async with session_factory() as session:
        tampered_args = {"doc_id": "doc-100", "operation": "tampered_write"}
        with pytest.raises(ValueError, match="Payload hash mismatch"):
            await consume_approval_atomic(
                session,
                app_id_3,
                tampered_args,
                profile_id="profile_main",
                tool_name="store_record",
                agent_id="specialist_alpha",
            )

    await engine.dispose()


# ============================================================================
# 6. Response Synthesizer Card Rendering and Tool Calls Packaging
# ============================================================================


def test_response_synthesizer_staged_action_card_formatting():
    """Verify ResponseSynthesizerNode formats Section 6 staged action cards per ADR §2.11 item 6."""
    synth = ResponseSynthesizerNode()
    state: Dict[str, Any] = {
        "deliberation_state": {
            "panel_id": "panel_alpha",
            "active_proposals": {
                "specialist_alpha": {
                    "agent_id": "specialist_alpha",
                    "round_num": 1,
                    "scope": "scope_alpha",
                    "summary": "Alpha summary",
                    "recommendations": ["Do alpha"],
                    "resource_claims": {},
                    "staged_actions": [
                        {
                            "agent_id": "specialist_alpha",
                            "tool_name": "workspace-note",
                            "tool_args": {"title": "Summary Note"},
                            "rationale": "Record draft notes for review",
                            "risk_tier": "write_local",
                        }
                    ],
                }
            },
            "critiques": {},
            "proposals": {},
            "missing_agents": [],
            "shared_constraints": [],
        }
    }

    full_output = synth.synthesize_deliberation(state)

    assert "## Staged Actions for Human Approval" in full_output
    assert "Staged Action 1: `specialist_alpha` → `workspace-note`" in full_output
    assert "**Risk Tier**: `write_local` (Forced Human Verification)" in full_output
    assert "**Rationale**: Record draft notes for review" in full_output
    assert "Awaiting human approval" in full_output


@pytest.mark.asyncio
async def test_response_synthesizer_packages_tool_calls():
    """Verify ResponseSynthesizerNode.execute packages tool_calls and routes to tools."""
    synth = ResponseSynthesizerNode()
    state: Dict[str, Any] = {
        "messages": [],
        "output": "Plan output",
        "deliberation_state": {
            "panel_id": "panel_alpha",
            "active_proposals": {
                "specialist_alpha": {
                    "agent_id": "specialist_alpha",
                    "round_num": 1,
                    "scope": "scope_alpha",
                    "summary": "Alpha plan",
                    "staged_actions": [
                        {
                            "agent_id": "specialist_alpha",
                            "tool_name": "workspace-note",
                            "tool_args": {"title": "Note"},
                            "rationale": "Staged write",
                            "risk_tier": "write_local",
                        }
                    ],
                }
            },
            "critiques": {},
            "proposals": {},
        },
    }

    result = await synth.execute(state)

    assert result["next_step"] == "tools"
    assert "tool_calls" in result
    assert len(result["tool_calls"]) == 1

    tc = result["tool_calls"][0]
    assert tc["name"] == "workspace-note"
    assert tc["args"] == {"title": "Note"}
    assert tc["agent_id"] == "specialist_alpha"
    assert tc["is_panel_staged"] is True
    assert "Review and approve staged panel actions" in result["follow_up_suggestions"]
