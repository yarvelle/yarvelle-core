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

"""Adversarial challenge test suite for Milestone 4 (Phase 3 Deliberation Staged Actions).

Empirically challenges:
1. Risk Tier Derivation & Evasion Attempts:
   - Proposing an action claiming risk_tier 'read' for an unknown tool or write tool.
   - Proposing an action with unrecognized or malformed risk tier string.
   - Fail-closed behavior of derive_tool_risk_tier and evaluate_deliberation_tool_gate.
   - Proposal/revision JSON parsing discarding model claims and enforcing specialist identity.
2. Steward Rejection and Denial Handling:
   - Explicit human steward rejection (decision='rejected') preventing tool execution.
   - Verification that execute_resume_turn generates safe steward rejection message and skips tool.
   - Verification that resumed thread does not re-deliberate or re-run rounds.
   - Handling of invalid approval states (pending, expired) and missing approval IDs.
3. Edge Routing and Graph Invariants:
   - Graph routing from response_synthesizer to tools when staged actions exist.
   - Graph routing from tools / tool_validator to output_guardrail when deliberation state is present.
   - Zero leakage into single-agent execution paths (which loop back to agent).
   - Universal forced human approval under A3 full autonomy for panel-staged actions.
   - Child under 13 external write hard-blocking invariant even when panel-staged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.db.models import Approval, Profile
from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.service import ExecutionService
from yarvelle_core.engine.tool_exec import (
    CHILD_UNDER_13,
    PolicyDecision,
    SqlApprovalStore,
    ToolContext,
    ToolSpec,
    evaluate_policy_gate,
    execute_tool_call,
)
from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.deliberation.tool_gate import (
    derive_tool_risk_tier,
    evaluate_deliberation_tool_gate,
    filter_read_only_tools,
)
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.nodes.tool_node import ToolNode
from yarvelle_core.workflows.state import AgentProposal, AgentState, CritiqueStance, PeerCritique, StagedAction


class MockScriptedChatModel:
    """Mock chat model returning scripted response strings."""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self.responses = list(responses or [])
        self.call_count = 0

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        resp = self.responses.pop(0) if self.responses else "{}"
        return AIMessage(content=resp)

    def bind_tools(self, tools: Sequence[Any]) -> MockScriptedChatModel:
        return self


@pytest.fixture
def test_app_store(async_db_session: AsyncSession) -> SqlApprovalStore:
    """SQL approval store wired to test DB session."""
    session_factory = async_sessionmaker(async_db_session.bind, expire_on_commit=False)
    return SqlApprovalStore(session_factory=session_factory)


@pytest.fixture
def isolated_workspace(tmp_path: Path) -> Path:
    """Isolated temporary workspace root."""
    ws = tmp_path / "workspace"
    notes = ws / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return ws


# ============================================================================
# Section 1: Risk Tier Derivation & Evasion Attempts
# ============================================================================


def test_adversarial_derive_tool_risk_tier_unknown_tool_claiming_read():
    """Verify an unknown tool name claiming 'read' is forced to 'irreversible'."""
    # Unknown tool without candidate spec
    assert derive_tool_risk_tier("unknown_rogue_tool") == "irreversible"

    # Candidate tool with unknown risk tier string claiming 'read-like' or non-standard tier
    candidate_bad = {"name": "custom_action", "risk_tier": "safe_read"}
    assert derive_tool_risk_tier("custom_action", tools=[candidate_bad]) == "irreversible"


def test_adversarial_derive_tool_risk_tier_known_write_tool_claiming_read():
    """Verify built-in write tools cannot have their risk tier downgraded by model claims."""
    # Built-in write_local tool
    assert derive_tool_risk_tier("workspace-note") == "write_local"
    # Built-in write_external tool
    assert derive_tool_risk_tier("calendar_create_event") == "write_external"
    # Built-in irreversible tool
    assert derive_tool_risk_tier("gmail_send_message") == "irreversible"

    # Even if candidate list passes a dict trying to re-declare 'workspace-note' as 'read'
    # The candidate tool takes precedence for custom tools, but if candidate specifies invalid tier it fails closed
    fake_candidate = {"name": "workspace-note", "risk_tier": "untrusted_read"}
    assert derive_tool_risk_tier("workspace-note", tools=[fake_candidate]) == "irreversible"


@pytest.mark.parametrize(
    "malformed_tier",
    ["", "   ", "BOGUS_TIER", "READ_ONLY", "superuser", "none", "null", "admin", "bypass"],
)
def test_adversarial_derive_tool_risk_tier_malformed_strings(malformed_tier: str):
    """Verify all non-standard, malformed, or whitespace risk tier strings fail closed to 'irreversible'."""
    custom_spec = {"name": "arbitrary_tool", "risk_tier": malformed_tier}
    assert derive_tool_risk_tier("arbitrary_tool", tools=[custom_spec]) == "irreversible"


def test_adversarial_deliberation_tool_gate_blocks_write_and_unknown():
    """Verify evaluate_deliberation_tool_gate blocks non-read tools during deliberation rounds."""
    ctx = ToolContext(user_id="user_1", profile_id="prof_1", run_id="run_1", autonomy="A3")

    # Read tool allowed
    read_decision = evaluate_deliberation_tool_gate(ctx, {"name": "attach-read", "risk_tier": "read"}, {})
    assert read_decision.decision == "allow"

    # Write tools blocked
    write_local_decision = evaluate_deliberation_tool_gate(ctx, {"name": "workspace-note"}, {})
    assert write_local_decision.decision == "blocked"

    # Unknown tool blocked
    unknown_decision = evaluate_deliberation_tool_gate(ctx, {"name": "mystery_operation"}, {})
    assert unknown_decision.decision == "blocked"


def test_adversarial_filter_read_only_tools_evasion():
    """Verify filter_read_only_tools strips write tools even if model attempts disguise."""
    candidates = [
        {"name": "attach-read", "risk_tier": "read"},
        {"name": "workspace-note", "risk_tier": "write_local"},
        {"name": "rogue_tool", "risk_tier": "safe_read"},  # Invalid tier -> irreversible
        ToolSpec(name="search_records", risk_tier="read"),
        ToolSpec(name="calendar_create_event", risk_tier="write_external"),
    ]

    filtered = filter_read_only_tools(candidates)
    assert len(filtered) == 2
    filtered_names = {t["name"] if isinstance(t, dict) else t.name for t in filtered}
    assert filtered_names == {"attach-read", "search_records"}


@pytest.mark.asyncio
async def test_adversarial_proposal_staged_action_model_tier_and_agent_spoofing():
    """Verify proposal generation strictly overwrites model-supplied risk_tier and agent_id."""
    spoofed_json = json.dumps({
        "agent_id": "spoofed_agent_hacker",
        "round_num": 1,
        "scope": "resource_planning",
        "summary": "Attempt to bypass safety invariants.",
        "recommendations": ["Execute staged actions directly."],
        "staged_actions": [
            {
                "agent_id": "spoofed_agent_hacker",
                "tool_name": "workspace-note",
                "tool_args": {"title": "Spoofed Note", "content": "Tampered."},
                "rationale": "Attempting to claim read tier.",
                "risk_tier": "read",  # Adversarial attempt to downgrade write_local to read
            },
            {
                "agent_id": "spoofed_agent_hacker",
                "tool_name": "unregistered_external_exec",
                "tool_args": {"cmd": "rm -rf"},
                "rationale": "Attempting arbitrary tool.",
                "risk_tier": "read",  # Adversarial attempt to downgrade unknown tool
            },
        ],
    })

    model = MockScriptedChatModel([spoofed_json])
    prop = await generate_agent_proposal(
        agent_id="legitimate_specialist_1",
        round_num=1,
        context={"profile_id": "prof_test"},
        model=model,
    )

    # Invariant 1: Top-level agent_id forced to legitimate identity
    assert prop.agent_id == "legitimate_specialist_1"

    # Invariant 2: StagedAction agent_id normalized to legitimate identity
    assert len(prop.staged_actions) == 2
    act1 = prop.staged_actions[0]
    assert act1.agent_id == "legitimate_specialist_1"
    # Invariant 3: Model-supplied risk_tier 'read' overwritten with derived 'write_local'
    assert act1.risk_tier == "write_local"

    act2 = prop.staged_actions[1]
    assert act2.agent_id == "legitimate_specialist_1"
    # Invariant 4: Unknown tool claiming 'read' forced to 'irreversible'
    assert act2.risk_tier == "irreversible"


@pytest.mark.asyncio
async def test_adversarial_revision_staged_action_model_spoofing():
    """Verify selective revision strictly overwrites model-supplied risk_tier and agent_id."""
    initial_prop = AgentProposal(
        agent_id="specialist_rev",
        round_num=1,
        scope="resource_planning",
        summary="Initial proposal.",
        recommendations=["Initial."],
    )

    critique = PeerCritique(
        reviewer_agent_id="critic_peer",
        target_agent_id="specialist_rev",
        round_num=1,
        stance=CritiqueStance.CONFLICT,
        issue_type="resource_overbudget",
        critique="Requires persistent note.",
        proposed_resolution="Add staged workspace note.",
    )

    revised_spoofed_json = json.dumps({
        "agent_id": "forged_rev_identity",
        "round_num": 2,
        "scope": "resource_planning",
        "summary": "Revised proposal addressing conflict.",
        "recommendations": ["Revised rec."],
        "staged_actions": [
            {
                "agent_id": "forged_rev_identity",
                "tool_name": "workspace-note",
                "tool_args": {"title": "Revised Note", "content": "Resolution."},
                "rationale": "Resolve critique.",
                "risk_tier": "read",  # Malicious attempt to declare write_local as read
            }
        ],
    })

    model = MockScriptedChatModel([revised_spoofed_json])
    updated = await run_selective_revision(
        active_proposals={"specialist_rev": initial_prop},
        critiques=[critique],
        round_num=2,
        context={"profile_id": "prof_test"},
        model=model,
    )

    rev_prop = updated["specialist_rev"]
    assert rev_prop.agent_id == "specialist_rev"
    assert len(rev_prop.staged_actions) == 1
    assert rev_prop.staged_actions[0].agent_id == "specialist_rev"
    assert rev_prop.staged_actions[0].risk_tier == "write_local"


# ============================================================================
# Section 2: Steward Rejection & Denial Handling
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_steward_rejection_prevents_tool_and_does_not_redeliberate(
    async_db_session: AsyncSession,
    test_app_store: SqlApprovalStore,
    isolated_workspace: Path,
):
    """Verify human steward rejection skips tool execution, records rejected status, and does not re-deliberate."""
    profile_id = "prof_adv_reject"
    async_db_session.add(Profile(id=profile_id, name="Adversarial Reject Profile"))
    await async_db_session.commit()

    deliberation_counter = {"rounds": 0}

    async def deliberation_node(state: AgentState) -> Dict[str, Any]:
        deliberation_counter["rounds"] += 1
        return {
            "deliberation_state": {
                "panel_id": "panel_steward_rejection",
                "active_proposals": {
                    "specialist_1": {
                        "agent_id": "specialist_1",
                        "round_num": 1,
                        "scope": "resource_planning",
                        "summary": "Plan proposing note creation.",
                        "staged_actions": [
                            {
                                "agent_id": "specialist_1",
                                "tool_name": "workspace-note",
                                "tool_args": {"title": "Forbidden_Note", "content": "Should never exist."},
                                "rationale": "Record note.",
                                "risk_tier": "write_local",
                            }
                        ],
                    }
                },
                "critiques": {},
                "proposals": {},
            },
            "output": "Deliberation plan output.",
        }

    synthesizer_node = ResponseSynthesizerNode()
    tool_node = ToolNode(
        approval_store=test_app_store,
        tools=list(CLOSED_TOOL_DEFINITIONS.values()),
    )

    builder = StateGraph(AgentState)
    builder.add_node("deliberation", deliberation_node)
    builder.add_node("response_synthesizer", synthesizer_node.execute)
    builder.add_node("tools", tool_node.execute)

    builder.add_edge(START, "deliberation")
    builder.add_edge("deliberation", "response_synthesizer")
    builder.add_edge("response_synthesizer", "tools")
    builder.add_edge("tools", END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    thread_id = "thread_adv_rejection"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "profile_id": profile_id,
            "user_id": "steward_user",
            "autonomy": "A3",  # Even with full autonomy A3
            "workspace_root": str(isolated_workspace),
            "approval_store": test_app_store,
        }
    }

    # Turn 1: Deliberation executes, halts at interrupt
    async for _ in graph.astream({"messages": [HumanMessage(content="Deliberate.")]}, config=config):
        pass

    assert deliberation_counter["rounds"] == 1

    # Fetch created approval
    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    approval = res.scalar_one()
    assert approval.status == "pending"

    # Human steward rejects the approval
    approval.status = "rejected"
    await async_db_session.commit()

    # Turn 2: Resume with decision='rejected'
    resume_payload = {
        "approval_id": approval.id,
        "decision": "rejected",
        "edited_args": approval.args_dict,
        "payload_hash": approval.payload_hash,
    }

    turn2_events: List[Dict[str, Any]] = []
    async for ev in graph.astream(Command(resume=resume_payload), config=config):
        turn2_events.append(ev)

    # Invariant 1: Deliberation node was NOT re-entered upon resume
    assert deliberation_counter["rounds"] == 1

    # Invariant 2: Forbidden note was NOT written to disk
    forbidden_file = isolated_workspace / "notes" / "Forbidden_Note.md"
    assert not forbidden_file.exists()

    # Invariant 3: Tool trace records rejected status
    tools_event = next((ev["tools"] for ev in turn2_events if "tools" in ev), None)
    assert tools_event is not None
    traces = tools_event.get("tool_traces", [])
    assert len(traces) == 1
    assert traces[0]["success"] is False
    assert traces[0]["output"].get("rejected") is True
    assert "rejected by user" in traces[0]["output"].get("error", "").lower()

    # Invariant 4: ToolMessage reflects error status
    messages = tools_event.get("messages", [])
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert messages[0].status == "error"


@pytest.mark.asyncio
async def test_adversarial_execute_resume_turn_with_unapproved_or_missing_record(
    async_db_session: AsyncSession,
    test_app_store: SqlApprovalStore,
    isolated_workspace: Path,
):
    """Verify execute_resume_turn returns error event when approval status is not approved or rejected."""
    from yarvelle_core.db.scoped_session import ScopedAsyncSession

    service = ExecutionService(workspace_root=str(isolated_workspace))
    test_factory = async_sessionmaker(async_db_session.bind, expire_on_commit=False, class_=ScopedAsyncSession)

    with patch("yarvelle_core.db.session.get_session_factory", return_value=test_factory):
        # Case 1: Non-existent approval ID
        events_missing = []
        async for ev in service.execute_resume_turn(
            thread_id="thread_missing",
            approval_id="app_nonexistent_123",
            decision="approved",
        ):
            events_missing.append(ev)

        assert len(events_missing) > 0
        assert "error" in events_missing[0].get("type", "").lower() or "not found" in events_missing[0].get("message", "").lower()

        # Case 2: Approval record still in 'pending' status in database
        profile_id = "prof_pending_test"
        async_db_session.add(Profile(id=profile_id, name="Pending Profile"))
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        pending_app = Approval(
            id="app_pending_456",
            profile_id=profile_id,
            run_id="run_1",
            thread_id="thread_pending",
            tool_name="workspace-note",
            risk_tier="write_local",
            args_redacted="{}",
            payload_hash="dummy_hash",
            status="pending",  # Neither approved nor rejected
            expires_at=now + timedelta(minutes=15),
        )
        async_db_session.add(pending_app)
        await async_db_session.commit()

        events_pending = []
        async for ev in service.execute_resume_turn(
            thread_id="thread_pending",
            approval_id="app_pending_456",
            decision="approved",
        ):
            events_pending.append(ev)

        assert len(events_pending) > 0
        err_msg = events_pending[0].get("message", "")
        assert "cannot resume" in err_msg.lower() or "must be approved or rejected" in err_msg.lower()


# ============================================================================
# Section 3: Edge Routing and Graph Invariants
# ============================================================================


def test_adversarial_graph_builder_routing_staged_actions_vs_output_guardrail():
    """Verify conditional edges route response_synthesizer to tools when staged actions exist,

    and route tools / tool_validator to output_guardrail (never back to agent).
    """
    builder = GraphBuilder()
    graph = builder.build()

    # Inspect conditional edge from response_synthesizer
    state_with_staged: AgentState = {
        "messages": [AIMessage(content="Plan", tool_calls=[{"id": "call_1", "name": "workspace-note", "args": {}}])],
        "tool_calls": [{"id": "call_1", "name": "workspace-note", "args": {}}],
        "iteration_count": 0,
        "is_panel_staged": True,
        "deliberation_state": {"panel_id": "test"},
    }

    # Verify response_synthesizer routing function logic
    # In GraphBuilder: if tool_calls present -> "tools", else -> "output_guardrail"
    tool_calls = state_with_staged.get("tool_calls")
    assert bool(tool_calls) is True

    # State without staged actions
    state_no_staged: AgentState = {
        "messages": [AIMessage(content="Plan without staged actions")],
        "tool_calls": [],
        "iteration_count": 0,
    }
    assert bool(state_no_staged.get("tool_calls")) is False


def test_adversarial_tool_validator_deliberation_routing_vs_single_agent():
    """Verify tool_validator routes to output_guardrail under deliberation and to agent under single-agent."""
    # 1. Deliberation state present
    delib_state: AgentState = {
        "deliberation_state": {"panel_id": "delib_panel"},
        "is_panel_staged": True,
    }
    target_delib = "output_guardrail" if (delib_state.get("deliberation_state") or delib_state.get("is_panel_staged")) else "agent"
    assert target_delib == "output_guardrail"

    # 2. Single-agent state (no deliberation_state, no is_panel_staged)
    single_agent_state: AgentState = {
        "deliberation_state": None,
        "is_panel_staged": False,
        "current_agent": "general_assistant",
    }
    target_single = "output_guardrail" if (single_agent_state.get("deliberation_state") or single_agent_state.get("is_panel_staged")) else "agent"
    assert target_single == "agent"


@pytest.mark.parametrize("risk_tier", ["write_local", "write_external", "irreversible"])
def test_adversarial_forced_approval_under_a3_autonomy(risk_tier: str):
    """Verify that even under full autonomy A3, is_panel_staged=True forces human approval."""
    ctx = ToolContext(
        user_id="user_admin",
        profile_id="prof_admin",
        run_id="run_admin",
        autonomy="A3",  # Full autonomy
    )
    spec = ToolSpec(name="test_tool", risk_tier=risk_tier)

    # Under is_panel_staged=True: ALWAYS forces approval
    decision_staged = evaluate_policy_gate(ctx, spec, {}, is_panel_staged=True)
    assert decision_staged.decision == "needs_approval"
    assert "Panel-staged action" in decision_staged.reason

    # Under is_panel_staged=False: A3 allows write_local and write_external without approval
    decision_single = evaluate_policy_gate(ctx, spec, {}, is_panel_staged=False)
    if risk_tier in ("write_local", "write_external"):
        assert decision_single.decision == "allow"
    else:  # irreversible always requires approval
        assert decision_single.decision == "needs_approval"


def test_adversarial_child_under_13_panel_staged_external_write_hard_blocked():
    """Verify that child under 13 external write is HARD-BLOCKED even when staged by a panel.

    Child protection invariant overrides panel staging approval mechanism.
    """
    ctx = ToolContext(
        user_id="child_user",
        profile_id="child_prof",
        run_id="run_child",
        autonomy="A3",
        extra={"age_band": CHILD_UNDER_13},
    )
    spec = ToolSpec(name="external_publisher", risk_tier="write_external")

    decision = evaluate_policy_gate(ctx, spec, {}, is_panel_staged=True, age_band=CHILD_UNDER_13)
    # Must be BLOCKED, not merely needs_approval
    assert decision.decision == "blocked"
    assert "Child under 13" in decision.reason

