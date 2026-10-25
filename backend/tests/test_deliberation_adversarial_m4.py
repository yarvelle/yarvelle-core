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

"""Adversarial stress-test challenge suite for Milestone 4 (Phase 3 Staged Actions & Resumed Turns).

Empirically challenges:
1. Autonomy bypass & down-rating evasion:
   - Full A3 autonomy under is_panel_staged=True across write_local, write_external, and irreversible.
   - Age band Child Under 13 hard-blocks external writes even when panel-staged.
   - Verification that single-agent autonomy (is_panel_staged=False) remains completely unregressed.
2. Cryptographic parameter binding & identity integrity:
   - Replay attacks on consumed approval tokens.
   - High-concurrency race conditions (double-spend attacks on single-use approval tokens).
   - Tool arguments tampering, key omission, value mutation, type confusion, and canonical JSON invariance.
   - Specialist agent identity spoofing and tampering.
   - Profile ID and tool name tampering.
   - Status checks on pending, rejected, and expired tokens.
3. Checkpointed resumption & zero-redeliberation invariant:
   - Resuming via Command(resume=...) must NEVER re-execute propose, critique, or revise rounds.
   - Resuming directly at ToolNode with tampered args fails closed without executing the tool.
4. Deterministic tier derivation evasion:
   - Untrusted model proposals claiming 'read' for write tools are strictly overridden.
   - Unknown tools strictly fail closed to 'irreversible'.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yarvelle_core.api.approvals import consume_approval_atomic
from yarvelle_core.db.models import Approval, Base, Profile
from yarvelle_core.engine.tool_exec import (
    PolicyDecision,
    SqlApprovalStore,
    ToolContext,
    ToolSpec,
    compute_action_binding_hash,
    compute_payload_hash,
    evaluate_policy_gate,
)
from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal
from yarvelle_core.workflows.deliberation.tool_gate import (
    derive_tool_risk_tier,
    evaluate_deliberation_tool_gate,
)
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.nodes.tool_node import ToolNode
from yarvelle_core.workflows.state import AgentState


class MockScriptedModel:
    """Mock language model returning pre-scripted responses."""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self.responses = list(responses or [])
        self.call_count = 0

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        resp_content = self.responses.pop(0) if self.responses else "{}"
        return AIMessage(content=resp_content)

    def bind_tools(self, tools: Sequence[Any]) -> MockScriptedModel:
        return self


@pytest.fixture
def workspace_env(tmp_path: Path) -> Path:
    """Isolated workspace root."""
    ws = tmp_path / "workspace"
    notes = ws / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return ws


# ============================================================================
# 1. Adversarial Autonomy Testing (A3, Edge Cases, Child Under 13)
# ============================================================================


@pytest.mark.parametrize("tier", ["write_local", "write_external", "irreversible", "bogus_tier", ""])
def test_adversarial_autonomy_a3_all_tiers_require_approval_when_panel_staged(tier: str):
    """Adversarial stress: Autonomy A3 MUST NOT bypass human approval when is_panel_staged=True."""
    spec = ToolSpec(name="test_tool", risk_tier=tier if tier != "bogus_tier" else "unrecognized")
    args = {"action": "execute_test"}

    # Test is_panel_staged passed via argument
    ctx = ToolContext(
        user_id="user_adv",
        profile_id="profile_adv",
        autonomy="A3",
        is_panel_staged=True,
    )
    decision = evaluate_policy_gate(ctx, spec, args, is_panel_staged=True)
    assert decision.decision == "needs_approval"
    assert decision.needs_approval is True
    assert decision.allowed is False

    # Test is_panel_staged set on ctx only
    decision_ctx = evaluate_policy_gate(ctx, spec, args)
    assert decision_ctx.decision == "needs_approval"
    assert decision_ctx.needs_approval is True

    # Test is_panel_staged set in ctx.extra
    ctx_extra = ToolContext(
        user_id="user_adv",
        profile_id="profile_adv",
        autonomy="A3",
        is_panel_staged=False,
        extra={"is_panel_staged": True},
    )
    decision_extra = evaluate_policy_gate(ctx_extra, spec, args)
    assert decision_extra.decision == "needs_approval"
    assert decision_extra.needs_approval is True


def test_adversarial_single_agent_a3_unregressed():
    """Verify single-agent autonomy (is_panel_staged=False) remains completely unregressed under A3."""
    ctx = ToolContext(
        user_id="user_adv",
        profile_id="profile_adv",
        autonomy="A3",
        is_panel_staged=False,
    )
    args = {"action": "execute_test"}

    # read is allowed
    dec_read = evaluate_policy_gate(ctx, ToolSpec(name="t1", risk_tier="read"), args)
    assert dec_read.decision == "allow"
    assert dec_read.allowed is True

    # write_local is allowed
    dec_local = evaluate_policy_gate(ctx, ToolSpec(name="t2", risk_tier="write_local"), args)
    assert dec_local.decision == "allow"
    assert dec_local.allowed is True

    # write_external is allowed
    dec_ext = evaluate_policy_gate(ctx, ToolSpec(name="t3", risk_tier="write_external"), args)
    assert dec_ext.decision == "allow"
    assert dec_ext.allowed is True

    # irreversible ALWAYS requires approval even under A3
    dec_irrev = evaluate_policy_gate(ctx, ToolSpec(name="t4", risk_tier="irreversible"), args)
    assert dec_irrev.decision == "needs_approval"
    assert dec_irrev.allowed is False


def test_adversarial_child_under_13_hard_block_overrides_panel_approval():
    """Adversarial stress: Panel-staged external writes for Child Under 13 must be BLOCKED, not approved."""
    spec_ext = ToolSpec(name="network_sync", risk_tier="write_external")
    ctx_child = ToolContext(
        user_id="child_user",
        profile_id="child_profile",
        autonomy="A3",
        is_panel_staged=True,
        extra={"age_band": "child_under_13"},
    )
    decision = evaluate_policy_gate(ctx_child, spec_ext, {"host": "example.org"}, is_panel_staged=True)
    # MUST be blocked (fail-closed law requirement), NEVER needs_approval
    assert decision.decision == "blocked"
    assert decision.allowed is False
    assert decision.needs_approval is False


# ============================================================================
# 2. Cryptographic Parameter Binding & Identity Integrity (Adversarial)
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_token_replay_rejected():
    """Adversarial attack: Replaying a consumed approval token must fail closed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tool_args = {"action": "deploy_step", "index": 42}
    payload_h = compute_payload_hash(tool_args)
    now = datetime.now(timezone.utc)
    app_id = "app_replay_target"

    async with session_factory() as session:
        session.add(
            Approval(
                id=app_id,
                profile_id="prof_replay",
                run_id="run_1",
                agent_id="specialist_ops",
                tool_name="deploy_tool",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="approved",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        await session.commit()

    # First consumption: SUCCESS
    async with session_factory() as session:
        consumed = await consume_approval_atomic(
            session,
            app_id,
            tool_args,
            profile_id="prof_replay",
            tool_name="deploy_tool",
            agent_id="specialist_ops",
        )
        assert consumed == app_id

    # Second consumption (Replay 1): MUST FAIL
    async with session_factory() as session:
        with pytest.raises(ValueError, match="cannot consume|already been consumed"):
            await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="prof_replay",
                tool_name="deploy_tool",
                agent_id="specialist_ops",
            )

    # Third consumption (Replay 2): MUST FAIL
    async with session_factory() as session:
        with pytest.raises(ValueError, match="cannot consume|already been consumed"):
            await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="prof_replay",
                tool_name="deploy_tool",
                agent_id="specialist_ops",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_concurrent_double_spend_race_condition():
    """Adversarial attack: 20 concurrent tasks attempting to consume the same approval token simultaneously."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tool_args = {"claim_id": "c-999"}
    payload_h = compute_payload_hash(tool_args)
    now = datetime.now(timezone.utc)
    app_id = "app_race_target"

    async with session_factory() as session:
        session.add(
            Approval(
                id=app_id,
                profile_id="prof_race",
                run_id="run_race",
                agent_id="specialist_race",
                tool_name="race_tool",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="approved",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        await session.commit()

    async def _try_consume():
        async with session_factory() as session:
            return await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="prof_race",
                tool_name="race_tool",
                agent_id="specialist_race",
            )

    results = await asyncio.gather(*[_try_consume() for _ in range(20)], return_exceptions=True)

    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, Exception)]

    # Invariant: EXACTLY 1 caller succeeds; all other 19 callers get rejected!
    assert len(successes) == 1
    assert len(failures) == 19
    for exc in failures:
        assert isinstance(exc, ValueError)

    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_argument_tampering_variations():
    """Adversarial attack: Test multiple mutations of tool arguments against payload hash."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    base_args = {"alpha": 100, "beta": ["x", "y"], "gamma": {"nested": True}}
    payload_h = compute_payload_hash(base_args)
    now = datetime.now(timezone.utc)
    app_id = "app_args_tamper"

    async with session_factory() as session:
        session.add(
            Approval(
                id=app_id,
                profile_id="prof_args",
                run_id="run_1",
                agent_id="spec_1",
                tool_name="t_args",
                args_redacted=json.dumps(base_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="approved",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        await session.commit()

    mutations = [
        {"alpha": 101, "beta": ["x", "y"], "gamma": {"nested": True}},  # Value modified
        {"alpha": 100, "gamma": {"nested": True}},  # Key omitted
        {"alpha": 100, "beta": ["x", "y"], "gamma": {"nested": True}, "extra": 1},  # Key injected
        {"alpha": "100", "beta": ["x", "y"], "gamma": {"nested": True}},  # Type confusion (int -> str)
        {"alpha": 100, "beta": ["y", "x"], "gamma": {"nested": True}},  # Array order changed
        {"alpha": 100, "beta": ["x", "y"], "gamma": {"nested": False}},  # Nested value modified
    ]

    for tampered in mutations:
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Payload hash mismatch"):
                await consume_approval_atomic(
                    session,
                    app_id,
                    tampered,
                    profile_id="prof_args",
                    tool_name="t_args",
                    agent_id="spec_1",
                )

    # BUT permutation of dictionary keys produces identical canonical JSON and matches!
    reordered_keys = {"gamma": {"nested": True}, "alpha": 100, "beta": ["x", "y"]}
    async with session_factory() as session:
        consumed_id = await consume_approval_atomic(
            session,
            app_id,
            reordered_keys,
            profile_id="prof_args",
            tool_name="t_args",
            agent_id="spec_1",
        )
        assert consumed_id == app_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_agent_identity_spoofing():
    """Adversarial attack: Specialist B attempts to consume an approval issued to Specialist A."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tool_args = {"note": "confidential"}
    payload_h = compute_payload_hash(tool_args)
    now = datetime.now(timezone.utc)
    app_id = "app_spoof_target"

    async with session_factory() as session:
        session.add(
            Approval(
                id=app_id,
                profile_id="prof_spoof",
                run_id="run_1",
                agent_id="specialist_authorized",
                tool_name="note_tool",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="approved",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        await session.commit()

    # Attacker 1: spoofed agent name
    async with session_factory() as session:
        with pytest.raises(ValueError, match="different agent"):
            await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="prof_spoof",
                tool_name="note_tool",
                agent_id="specialist_adversary",
            )

    # Attacker 2: trailing whitespace injection
    async with session_factory() as session:
        with pytest.raises(ValueError, match="different agent"):
            await consume_approval_atomic(
                session,
                app_id,
                tool_args,
                profile_id="prof_spoof",
                tool_name="note_tool",
                agent_id="specialist_authorized ",
            )

    # Authorized consumer succeeds
    async with session_factory() as session:
        res = await consume_approval_atomic(
            session,
            app_id,
            tool_args,
            profile_id="prof_spoof",
            tool_name="note_tool",
            agent_id="specialist_authorized",
        )
        assert res == app_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_adversarial_expired_and_unapproved_states():
    """Adversarial stress: Tokens in pending, rejected, or expired states cannot be consumed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tool_args = {"data": "test"}
    payload_h = compute_payload_hash(tool_args)
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # Pending token
        session.add(
            Approval(
                id="app_pending",
                profile_id="p1",
                run_id="r1",
                agent_id="a1",
                tool_name="t1",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="pending",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        # Rejected token
        session.add(
            Approval(
                id="app_rejected",
                profile_id="p1",
                run_id="r1",
                agent_id="a1",
                tool_name="t1",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="rejected",
                expires_at=now + timedelta(minutes=10),
                created_at=now,
            )
        )
        # Expired token
        session.add(
            Approval(
                id="app_expired",
                profile_id="p1",
                run_id="r1",
                agent_id="a1",
                tool_name="t1",
                args_redacted=json.dumps(tool_args),
                payload_hash=payload_h,
                risk_tier="write_local",
                status="approved",
                expires_at=now - timedelta(minutes=5),  # in past!
                created_at=now - timedelta(minutes=15),
            )
        )
        await session.commit()

    # Pending cannot consume
    async with session_factory() as session:
        with pytest.raises(ValueError, match="status 'pending'"):
            await consume_approval_atomic(session, "app_pending", tool_args, profile_id="p1", tool_name="t1", agent_id="a1")

    # Rejected cannot consume
    async with session_factory() as session:
        with pytest.raises(ValueError, match="status 'rejected'"):
            await consume_approval_atomic(session, "app_rejected", tool_args, profile_id="p1", tool_name="t1", agent_id="a1")

    # Expired token raises error and updates status to expired
    async with session_factory() as session:
        with pytest.raises(ValueError, match="has expired"):
            await consume_approval_atomic(session, "app_expired", tool_args, profile_id="p1", tool_name="t1", agent_id="a1")

    # Verify status changed in DB to expired
    async with session_factory() as session:
        rec = await session.get(Approval, "app_expired")
        assert rec is not None
        assert rec.status == "expired"

    await engine.dispose()


# ============================================================================
# 3. Checkpointed Resumption: Deliberation Node Execution Invariant
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_resume_never_redeliberates(
    async_db_session: AsyncSession,
    workspace_env: Path,
):
    """Adversarial stress: Prove empirically that deliberation nodes are called 0 times on resume."""
    session_factory = async_sessionmaker(async_db_session.bind, expire_on_commit=False)
    app_store = SqlApprovalStore(session_factory=session_factory)

    profile_id = "prof_adversarial_resume"
    async_db_session.add(Profile(id=profile_id, name="Adversarial Profile"))
    await async_db_session.commit()

    execution_counters = {
        "propose_phase": 0,
        "peer_critiques": 0,
        "selective_revision": 0,
        "synthesizer": 0,
    }

    # Deliberation graph node wrapping all 3 sub-phases
    async def monitored_deliberation_node(state: AgentState) -> Dict[str, Any]:
        execution_counters["propose_phase"] += 1
        execution_counters["peer_critiques"] += 1
        execution_counters["selective_revision"] += 1

        delib_state = {
            "panel_id": "panel_empiric",
            "active_proposals": {
                "specialist_alpha": {
                    "agent_id": "specialist_alpha",
                    "round_num": 1,
                    "scope": "domain_neutral_scope",
                    "summary": "Coordinated plan with staged action.",
                    "staged_actions": [
                        {
                            "agent_id": "specialist_alpha",
                            "tool_name": "workspace-note",
                            "tool_args": {"title": "Deliberation Record", "content": "Proof of execution."},
                            "rationale": "Record consensus to workspace.",
                            "risk_tier": "write_local",
                        }
                    ],
                }
            },
            "critiques": {},
            "proposals": {},
        }
        return {
            "deliberation_state": delib_state,
            "output": "Deliberation plan.",
        }

    synthesizer = ResponseSynthesizerNode()

    async def monitored_synthesizer_node(state: AgentState) -> Dict[str, Any]:
        execution_counters["synthesizer"] += 1
        return await synthesizer.execute(state)

    tool_node = ToolNode(
        approval_store=app_store,
        tools=list(CLOSED_TOOL_DEFINITIONS.values()),
    )

    builder = StateGraph(AgentState)
    builder.add_node("deliberation", monitored_deliberation_node)
    builder.add_node("response_synthesizer", monitored_synthesizer_node)
    builder.add_node("tools", tool_node.execute)

    builder.add_edge(START, "deliberation")
    builder.add_edge("deliberation", "response_synthesizer")

    def route_synth(state: AgentState) -> str:
        if state.get("tool_calls"):
            return "tools"
        return END

    builder.add_conditional_edges("response_synthesizer", route_synth, {"tools": "tools", END: END})

    def route_tools(state: AgentState) -> str:
        # Panel staged routing directly terminates without looping to agent
        if state.get("deliberation_state") or state.get("is_panel_staged"):
            return END
        return END

    builder.add_conditional_edges("tools", route_tools, {END: END})

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    thread_id = "th_adversarial_empirical"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "profile_id": profile_id,
            "user_id": "user_steward",
            "autonomy": "A3",
            "workspace_root": str(workspace_env),
            "approval_store": app_store,
        }
    }

    initial_state = {
        "messages": [HumanMessage(content="Action.")],
        "workspace_root": str(workspace_env),
        "profile_id": profile_id,
        "user_id": "user_steward",
    }
    # Turn 1: Initial invocation
    turn1_chunks = []
    async for ev in graph.astream(initial_state, config=config):
        turn1_chunks.append(ev)

    # Turn 1 assertions
    assert execution_counters["propose_phase"] == 1
    assert execution_counters["peer_critiques"] == 1
    assert execution_counters["selective_revision"] == 1
    assert execution_counters["synthesizer"] == 1

    # Check pending approval
    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    approval = res.scalar_one()
    assert approval.status == "pending"

    # Turn 2: Resumption after approval
    approval.status = "approved"
    await async_db_session.commit()

    resume_payload = {
        "approval_id": approval.id,
        "decision": "approved",
        "edited_args": approval.args_dict,
        "payload_hash": approval.payload_hash,
    }

    turn2_chunks = []
    async for ev in graph.astream(Command(resume=resume_payload), config=config):
        turn2_chunks.append(ev)

    # EMPIRICAL PROOF: Deliberation and Synthesizer counters did NOT increment!
    assert execution_counters["propose_phase"] == 1, "Propose phase was re-executed on resume!"
    assert execution_counters["peer_critiques"] == 1, "Peer critiques was re-executed on resume!"
    assert execution_counters["selective_revision"] == 1, "Selective revision was re-executed on resume!"
    assert execution_counters["synthesizer"] == 1, "Synthesizer was re-executed on resume!"

    # Tool executed and note was created
    created_notes = list(workspace_env.glob("**/*.md"))
    assert len(created_notes) == 1
    assert "Proof of execution." in created_notes[0].read_text(encoding="utf-8")


# ============================================================================
# 4. Deterministic Risk Tier Derivation Evasion
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_proposal_tier_forgery_overridden():
    """Adversarial stress: Specialist proposal attempting to forge 'read' tier for an external write tool."""
    raw_forged_json = json.dumps({
        "agent_id": "forger_agent",
        "round_num": 1,
        "scope": "network_scope",
        "summary": "Summary",
        "recommendations": ["Rec"],
        "resource_claims": {},
        "staged_actions": [
            {
                "tool_name": "calendar_create_event",
                "tool_args": {"title": "Sync Event"},
                "rationale": "External sync",
                "risk_tier": "read",  # FORGERY: claims read for write_external tool!
            },
            {
                "tool_name": "unregistered_destructive_tool",
                "tool_args": {"target": "all"},
                "rationale": "Destructive op",
                "risk_tier": "read",  # FORGERY: claims read for unknown tool!
            },
        ],
    })

    model = MockScriptedModel([raw_forged_json])
    prop = await generate_agent_proposal(
        agent_id="specialist_forger",
        round_num=1,
        context={"prompt": "Plan sync"},
        model=model,
        scope="network_scope",
    )

    # Both forgeries MUST be overridden deterministically
    assert prop.staged_actions[0].tool_name == "calendar_create_event"
    assert prop.staged_actions[0].risk_tier == "write_external"

    assert prop.staged_actions[1].tool_name == "unregistered_destructive_tool"
    assert prop.staged_actions[1].risk_tier == "irreversible"
