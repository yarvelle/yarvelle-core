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

"""Comprehensive Integration Tests for Checkpointed Resume of Deliberation Staged Actions.

Verifies:
1. End-to-end checkpointed pause and resume with LangGraph MemorySaver.
2. Deliberation rounds (propose, critique, revise) are NOT re-executed upon resumption.
3. Cryptographic parameter binding verification (agent_id, tool_name, profile_id, canonical hash).
4. Tampered payload arguments and tampered agent_id fail cryptographic verification.
5. Steward rejection handling on resumed thread.
6. Forced approval invariant across all autonomy levels (A0-A3) during panel execution.
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
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.db.models import Approval, Profile
from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.tool_exec import (
    SqlApprovalStore,
    ToolContext,
    ToolSpec,
    compute_action_binding_hash,
)
from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS
from yarvelle_core.workflows.nodes.response_synthesizer_node import ResponseSynthesizerNode
from yarvelle_core.workflows.nodes.tool_node import ToolNode
from yarvelle_core.workflows.state import AgentState


@pytest.fixture
def mock_app_store(async_db_session: AsyncSession) -> SqlApprovalStore:
    """SQL approval store wired to test DB session."""
    session_factory = async_sessionmaker(async_db_session.bind, expire_on_commit=False)
    return SqlApprovalStore(session_factory=session_factory)


@pytest.fixture
def workspace_env(tmp_path: Path) -> Path:
    """Isolated workspace root."""
    ws = tmp_path / "workspace"
    notes = ws / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.mark.asyncio
async def test_deliberation_staged_action_interrupt_and_resumed_execution(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
    workspace_env: Path,
):
    """Verify that deliberation staged actions pause at interrupt and resume without re-running deliberation."""
    profile_id = "profile_omega"
    async_db_session.add(Profile(id=profile_id, name="Omega Profile"))
    await async_db_session.commit()

    deliberation_call_counter = {"propose": 0, "critique": 0, "revise": 0}

    # 1. Deliberation mock node simulating proposal phase
    async def deliberation_node(state: AgentState) -> Dict[str, Any]:
        deliberation_call_counter["propose"] += 1
        deliberation_call_counter["critique"] += 1
        deliberation_call_counter["revise"] += 1

        delib_state = {
            "panel_id": "panel_omega",
            "active_proposals": {
                "specialist_alpha": {
                    "agent_id": "specialist_alpha",
                    "round_num": 1,
                    "scope": "resource_planning",
                    "summary": "Allocate project resources and document milestones.",
                    "staged_actions": [
                        {
                            "agent_id": "specialist_alpha",
                            "tool_name": "workspace-note",
                            "tool_args": {"title": "Milestone Plan", "content": "Phase 1 verified."},
                            "rationale": "Record milestone decisions to local workspace.",
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
            "output": "Deliberation achieved consensus on project milestones.",
        }

    # 2. Response synthesizer node
    synthesizer_node = ResponseSynthesizerNode()

    # 3. Tool node with real workspace-note execution
    tool_node = ToolNode(
        approval_store=mock_app_store,
        tools=list(CLOSED_TOOL_DEFINITIONS.values()),
    )

    # 4. Output guardrail node
    async def output_guardrail_node(state: AgentState) -> Dict[str, Any]:
        return {"sanitized_output": "verified_output"}

    # 5. Assemble graph
    builder = StateGraph(AgentState)
    builder.add_node("deliberation", deliberation_node)
    builder.add_node("response_synthesizer", synthesizer_node.execute)
    builder.add_node("tools", tool_node.execute)
    builder.add_node("output_guardrail", output_guardrail_node)

    builder.add_edge(START, "deliberation")
    builder.add_edge("deliberation", "response_synthesizer")

    def route_after_synthesizer(state: AgentState) -> str:
        if state.get("tool_calls"):
            return "tools"
        return "output_guardrail"

    builder.add_conditional_edges(
        "response_synthesizer",
        route_after_synthesizer,
        {"tools": "tools", "output_guardrail": "output_guardrail"},
    )

    def route_after_tools(state: AgentState) -> str:
        if state.get("deliberation_state") or state.get("is_panel_staged"):
            return "output_guardrail"
        return END

    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {"output_guardrail": "output_guardrail", END: END},
    )
    builder.add_edge("output_guardrail", END)

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    thread_id = "test_deliberation_thread_alpha"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "profile_id": profile_id,
            "user_id": "user_steward",
            "autonomy": "A3",  # Even with A3, panel staged action MUST pause
            "workspace_root": str(workspace_env),
            "approval_store": mock_app_store,
        }
    }

    initial_state = {
        "messages": [HumanMessage(content="Coordinate project rollout.")],
        "workspace_root": str(workspace_env),
        "profile_id": profile_id,
        "user_id": "user_steward",
    }

    # -------------------------------------------------------------
    # TURN 1: Execute graph until it pauses for human approval
    # -------------------------------------------------------------
    turn1_events = []
    async for ev in graph.astream(initial_state, config=config):
        turn1_events.append(ev)

    # Verify deliberation ran in Turn 1
    assert deliberation_call_counter["propose"] == 1
    assert deliberation_call_counter["critique"] == 1
    assert deliberation_call_counter["revise"] == 1

    # Verify graph state is paused at interrupt
    cp_state = await checkpointer.aget(config)
    assert cp_state is not None
    checkpoint_channels = cp_state.get("channel_values", {})
    assert "deliberation_state" in checkpoint_channels
    assert checkpoint_channels["deliberation_state"]["panel_id"] == "panel_omega"

    # Verify pending approval was created in database
    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    pending_approvals = list(res.scalars().all())
    assert len(pending_approvals) == 1
    approval = pending_approvals[0]
    assert approval.tool_name == "workspace-note"
    assert approval.agent_id == "specialist_alpha"
    assert approval.profile_id == profile_id
    assert approval.status == "pending"

    # Verify the note has NOT been created yet in Turn 1
    note_files_turn1 = list(workspace_env.glob("**/*.md"))
    assert len(note_files_turn1) == 0

    # -------------------------------------------------------------
    # TURN 2: Resumption after human approval
    # -------------------------------------------------------------
    # Steward marks approval approved
    approval.status = "approved"
    await async_db_session.commit()

    resume_payload = {
        "approval_id": approval.id,
        "decision": "approved",
        "edited_args": approval.args_dict,
        "payload_hash": approval.payload_hash,
    }

    # Resume graph execution via Command
    resume_cmd = Command(resume=resume_payload)
    turn2_events = []
    async for ev in graph.astream(resume_cmd, config=config):
        turn2_events.append(ev)

    # CRITICAL INVARIANT: Deliberation functions were NOT re-executed on resume!
    assert deliberation_call_counter["propose"] == 1
    assert deliberation_call_counter["critique"] == 1
    assert deliberation_call_counter["revise"] == 1

    # Verify tool execution succeeded on resume
    final_cp = await checkpointer.aget(config)
    final_channels = final_cp.get("channel_values", {})
    assert final_channels.get("sanitized_output") == "verified_output"

    # Verify note file was created on resume
    note_files_turn2 = list(workspace_env.glob("**/*.md"))
    assert len(note_files_turn2) == 1
    note_file = note_files_turn2[0]
    assert note_file.name == "milestone-plan.md"
    content = note_file.read_text(encoding="utf-8")
    assert "Phase 1 verified." in content

    # Verify approval status is now consumed in DB
    consumed_app = await mock_app_store.get(approval.id)
    assert consumed_app is not None
    assert consumed_app.status == "consumed"


@pytest.mark.asyncio
async def test_deliberation_staged_action_tampered_payload_rejected(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
    workspace_env: Path,
):
    """Verify that tampering with tool arguments on resume fails cryptographic binding."""
    profile_id = "profile_sec"
    async_db_session.add(Profile(id=profile_id, name="Security Profile"))
    await async_db_session.commit()

    # 1. Deliberation mock node
    async def deliberation_node(state: AgentState) -> Dict[str, Any]:
        return {
            "deliberation_state": {
                "panel_id": "panel_security",
                "active_proposals": {
                    "specialist_alpha": {
                        "agent_id": "specialist_alpha",
                        "round_num": 1,
                        "scope": "security_boundary",
                        "summary": "Record audit summary.",
                        "staged_actions": [
                            {
                                "agent_id": "specialist_alpha",
                                "tool_name": "workspace-note",
                                "tool_args": {"title": "Legitimate Title", "content": "Legitimate content."},
                                "rationale": "Record security note.",
                                "risk_tier": "write_local",
                            }
                        ],
                    }
                },
                "critiques": {},
                "proposals": {},
            },
            "output": "Deliberation plan.",
        }

    synthesizer_node = ResponseSynthesizerNode()
    tool_node = ToolNode(
        approval_store=mock_app_store,
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

    thread_id = "test_tamper_thread"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "profile_id": profile_id,
            "user_id": "user_steward",
            "autonomy": "A1",
            "workspace_root": str(workspace_env),
            "approval_store": mock_app_store,
        }
    }

    # Turn 1: pause for approval
    async for _ in graph.astream({"messages": [HumanMessage(content="Action.")]}, config=config):
        pass

    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    approval = res.scalar_one()
    approval.status = "approved"
    await async_db_session.commit()

    # Turn 2: Tampered args in resume payload
    tampered_args = {"title": "Malicious Title", "content": "Malicious overwrite!"}
    resume_payload = {
        "approval_id": approval.id,
        "decision": "approved",
        "edited_args": tampered_args,
        "payload_hash": approval.payload_hash,  # Hash does not match tampered_args!
    }

    turn2_events = []
    async for ev in graph.astream(Command(resume=resume_payload), config=config):
        turn2_events.append(ev)

    # Verification: tool execution was refused due to signature mismatch
    tools_event = next((ev["tools"] for ev in turn2_events if "tools" in ev), None)
    assert tools_event is not None
    tool_msgs = tools_event.get("messages", [])
    assert len(tool_msgs) > 0
    t_msg = tool_msgs[0]
    assert t_msg.status == "error"
    assert "Payload hash mismatch" in t_msg.content or "Cryptographic" in t_msg.content or "fail-closed" in t_msg.content

    # Malicious file must NOT exist
    assert not (workspace_env / "notes" / "Malicious_Title.md").exists()


@pytest.mark.asyncio
async def test_deliberation_staged_action_agent_id_mismatch_rejected(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
):
    """Verify that approval consumption fails if agent_id does not match the bound specialist."""
    profile_id = "profile_audit"
    async_db_session.add(Profile(id=profile_id, name="Audit Profile"))
    await async_db_session.commit()

    tool_name = "workspace-note"
    args = {"title": "Audit Summary"}

    # Create approved token bound to specialist_alpha
    app_record = await mock_app_store.create_pending(
        approval_id="app_mismatch_1",
        profile_id=profile_id,
        run_id="run-1",
        tool_name=tool_name,
        args=args,
        risk_tier="write_local",
        agent_id="specialist_alpha",
    )

    stmt = select(Approval).where(Approval.id == "app_mismatch_1")
    res = await async_db_session.execute(stmt)
    rec = res.scalar_one()
    rec.status = "approved"
    await async_db_session.commit()

    # Attempt to consume with mismatched agent_id (specialist_beta)
    with pytest.raises(ValueError) as exc_info:
        await mock_app_store.consume_atomic(
            approval_id="app_mismatch_1",
            current_args=args,
            profile_id=profile_id,
            tool_name=tool_name,
            agent_id="specialist_beta",
        )
    assert "different agent" in str(exc_info.value)

    # Original token remains unconsumed
    async_db_session.expire_all()
    app_rec = await async_db_session.get(Approval, "app_mismatch_1")
    assert app_rec.status == "approved"

    # Consuming with matching agent_id succeeds
    consumed_id = await mock_app_store.consume_atomic(
        approval_id="app_mismatch_1",
        current_args=args,
        profile_id=profile_id,
        tool_name=tool_name,
        agent_id="specialist_alpha",
    )
    assert consumed_id == "app_mismatch_1"
    async_db_session.expire_all()
    app_rec_consumed = await async_db_session.get(Approval, "app_mismatch_1")
    assert app_rec_consumed.status == "consumed"


@pytest.mark.asyncio
async def test_deliberation_staged_action_steward_rejection(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
    workspace_env: Path,
):
    """Verify that when a human steward rejects a staged action, tool execution is cleanly skipped."""
    profile_id = "profile_rej"
    async_db_session.add(Profile(id=profile_id, name="Rejection Profile"))
    await async_db_session.commit()

    async def deliberation_node(state: AgentState) -> Dict[str, Any]:
        return {
            "deliberation_state": {
                "panel_id": "panel_reject",
                "active_proposals": {
                    "specialist_alpha": {
                        "agent_id": "specialist_alpha",
                        "round_num": 1,
                        "scope": "resource_planning",
                        "summary": "Plan requiring approval.",
                        "staged_actions": [
                            {
                                "agent_id": "specialist_alpha",
                                "tool_name": "workspace-note",
                                "tool_args": {"title": "Rejected Note", "content": "Never write."},
                                "rationale": "Record note.",
                                "risk_tier": "write_local",
                            }
                        ],
                    }
                },
                "critiques": {},
                "proposals": {},
            },
            "output": "Plan output.",
        }

    synthesizer_node = ResponseSynthesizerNode()
    tool_node = ToolNode(
        approval_store=mock_app_store,
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

    thread_id = "test_rejection_thread"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "profile_id": profile_id,
            "user_id": "user_steward",
            "autonomy": "A2",
            "workspace_root": str(workspace_env),
            "approval_store": mock_app_store,
        }
    }

    # Turn 1: pause
    async for _ in graph.astream({"messages": [HumanMessage(content="Action.")]}, config=config):
        pass

    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    approval = res.scalar_one()
    approval.status = "rejected"
    await async_db_session.commit()

    # Turn 2: resume with rejected decision
    resume_payload = {
        "approval_id": approval.id,
        "decision": "rejected",
        "edited_args": approval.args_dict,
        "payload_hash": approval.payload_hash,
    }

    turn2_events = []
    async for ev in graph.astream(Command(resume=resume_payload), config=config):
        turn2_events.append(ev)

    # Verify tool was NOT executed
    assert not (workspace_env / "notes" / "Rejected_Note.md").exists()

    tools_event = next((ev["tools"] for ev in turn2_events if "tools" in ev), None)
    assert tools_event is not None
    traces = tools_event.get("tool_traces", [])
    assert len(traces) > 0
    assert traces[0]["success"] is False
    assert traces[0]["output"].get("rejected") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("autonomy_level", ["A0", "A1", "A2", "A3"])
async def test_deliberation_staged_action_forced_approval_across_all_autonomy_levels(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
    workspace_env: Path,
    autonomy_level: str,
):
    """Verify that staged actions from deliberation panels force approval across all autonomy levels (A0-A3)."""
    profile_id = f"prof_{autonomy_level.lower()}"
    async_db_session.add(Profile(id=profile_id, name=f"Profile {autonomy_level}"))
    await async_db_session.commit()

    async def deliberation_node(state: AgentState) -> Dict[str, Any]:
        return {
            "deliberation_state": {
                "panel_id": f"panel_{autonomy_level}",
                "active_proposals": {
                    "specialist_alpha": {
                        "agent_id": "specialist_alpha",
                        "round_num": 1,
                        "scope": "resource_planning",
                        "summary": "Plan requiring verification.",
                        "staged_actions": [
                            {
                                "agent_id": "specialist_alpha",
                                "tool_name": "workspace-note",
                                "tool_args": {"title": f"Note {autonomy_level}", "content": "Audit text."},
                                "rationale": "Record note.",
                                "risk_tier": "write_local",
                            }
                        ],
                    }
                },
                "critiques": {},
                "proposals": {},
            },
            "output": "Plan output.",
        }

    synthesizer_node = ResponseSynthesizerNode()
    tool_node = ToolNode(
        approval_store=mock_app_store,
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

    config = {
        "configurable": {
            "thread_id": f"th_{autonomy_level}",
            "profile_id": profile_id,
            "user_id": "user_steward",
            "autonomy": autonomy_level,
            "workspace_root": str(workspace_env),
            "approval_store": mock_app_store,
        }
    }

    # Turn 1 MUST pause at interrupt even for A3
    turn1_events = []
    async for ev in graph.astream({"messages": [HumanMessage(content="Action.")]}, config=config):
        turn1_events.append(ev)

    interrupt_event = next((ev for ev in turn1_events if "__interrupt__" in ev), None)
    assert interrupt_event is not None, f"Autonomy {autonomy_level} failed to pause for human approval!"

    # Verify pending approval was created
    stmt = select(Approval).where(Approval.profile_id == profile_id)
    res = await async_db_session.execute(stmt)
    pending_approvals = list(res.scalars().all())
    assert len(pending_approvals) == 1
    assert pending_approvals[0].status == "pending"


@pytest.mark.asyncio
async def test_single_agent_vs_panel_staged_autonomy_contrast(
    async_db_session: AsyncSession,
    mock_app_store: SqlApprovalStore,
    workspace_env: Path,
):
    """Verify single-agent tool call executes freely under A3, while panel-staged call forces approval."""
    profile_id = "prof_contrast"
    async_db_session.add(Profile(id=profile_id, name="Contrast Profile"))
    await async_db_session.commit()

    tool_node = ToolNode(
        approval_store=mock_app_store,
        tools=list(CLOSED_TOOL_DEFINITIONS.values()),
    )

    ctx_single = ToolContext(
        user_id="user_steward",
        profile_id=profile_id,
        run_id="run_single",
        autonomy="A3",
        workspace_root=workspace_env,
        skills_dir=workspace_env / "skills",
        effective_tools=tuple(CLOSED_TOOL_DEFINITIONS.keys()),
        is_panel_staged=False,
    )

    ctx_panel = ToolContext(
        user_id="user_steward",
        profile_id=profile_id,
        run_id="run_panel",
        autonomy="A3",
        workspace_root=workspace_env,
        skills_dir=workspace_env / "skills",
        effective_tools=tuple(CLOSED_TOOL_DEFINITIONS.keys()),
        is_panel_staged=True,
    )

    spec = ToolSpec(name="workspace-note", risk_tier="write_local")
    args = {"title": "Contrast Note", "content": "Testing contrast"}

    from yarvelle_core.engine.tool_exec import evaluate_policy_gate

    # Single-agent at A3 allows execution without human approval
    decision_single = evaluate_policy_gate(ctx_single, spec, args, is_panel_staged=False)
    assert decision_single.decision == "allow"
    assert decision_single.allowed is True
    assert decision_single.needs_approval is False

    # Panel-staged at A3 FORCES human approval (needs_approval)
    decision_panel = evaluate_policy_gate(ctx_panel, spec, args, is_panel_staged=True)
    assert decision_panel.decision == "needs_approval"
    assert decision_panel.allowed is False
    assert decision_panel.needs_approval is True

