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

"""Unit and integration tests for framework multi-turn continuity and state retention.

Verifies:
1. State channel retention across consecutive turns (document_dossiers, attachments, notes).
2. Specialist system prompt refresh on routed follow-up turns.
3. Resumed turn ToolContext propagation in graph_config configurable.
4. Monotone TaintFlag persistence across multi-turn thread checkpoints.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.service import AgentExecutionService
from yarvelle_core.engine.tool_exec import TaintFlag, ToolContext, ToolSpec, UntrustedResult
from yarvelle_core.workflows.nodes.agent_execution_node import AgentExecutionNode
from yarvelle_core.workflows.nodes.agent_node import AgentNode
from yarvelle_core.workflows.nodes.tool_node import ToolNode
from yarvelle_core.workflows.state import AgentState


def _write_agent(root: Path, agent_id: str) -> None:
    """Helper to write a valid agent manifest and persona for testing."""
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": agent_id,
        "title": agent_id.replace("-", " ").title(),
        "description": f"{agent_id} coordinator",
        "persona": "persona.md",
        "tools": [],
        "skills": [],
    }
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (agent_dir / "persona.md").write_text(f"You are the {agent_id} agent.\n", encoding="utf-8")


class InMemoryCheckpointer:
    """Simple in-memory checkpointer double for multi-turn state testing."""

    def __init__(self, initial_channels: Optional[Dict[str, Any]] = None) -> None:
        self.channels = initial_channels or {}
        self.tuple_obj = MagicMock()
        self.tuple_obj.checkpoint = {"channel_values": self.channels}

    async def aget_tuple(self, config: Dict[str, Any]) -> Any:
        if self.channels:
            return self.tuple_obj
        return None

    def get_tuple(self, config: Dict[str, Any]) -> Any:
        if self.channels:
            return self.tuple_obj
        return None


# -------------------------------------------------------------------------
# 1. State Channel Persistence Across Turns
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_turn_state_channel_retention_when_no_new_inputs(tmp_path: Path) -> None:
    """Turn 2 without new attachments or dossiers preserves Turn 1 channel state."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "task-coordinator")

    turn1_channels = {
        "messages": [HumanMessage(content="Turn 1 input"), AIMessage(content="Turn 1 answer")],
        "attachments": ["document_1.pdf"],
        "document_dossiers": [{"dossier_id": "dos-1", "title": "Annual Summary"}],
        "notes": [{"note_id": "note-1", "content": "Review scheduled"}],
        "is_tainted": False,
    }
    checkpointer = InMemoryCheckpointer(turn1_channels)

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    captured_inputs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, initial_input: Dict[str, Any], config: Any, version: str) -> Any:
            captured_inputs.append(initial_input)
            if False:
                yield {}

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_turn(
            agent_id="task-coordinator",
            prompt="Turn 2 follow-up query",
            thread_id="th-multi-turn-1",
            user_id="user-1",
            profile_id="profile-1",
            attachments=None,  # No new attachments
        ):
            pass

    assert len(captured_inputs) == 1
    inp = captured_inputs[0]

    # Verify state channels are retained from checkpoint
    assert inp["attachments"] == ["document_1.pdf"]
    assert inp["document_dossiers"] == [{"dossier_id": "dos-1", "title": "Annual Summary"}]
    assert inp["notes"] == [{"note_id": "note-1", "content": "Review scheduled"}]
    # Messages only appends the new HumanMessage
    assert len(inp["messages"]) == 1
    assert inp["messages"][0].content == "Turn 2 follow-up query"


@pytest.mark.asyncio
async def test_multi_turn_state_channel_overwritten_when_new_attachments_supplied(tmp_path: Path) -> None:
    """Turn 2 with new attachments uses the new attachments."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "task-coordinator")

    turn1_channels = {
        "messages": [HumanMessage(content="Turn 1 input")],
        "attachments": ["old_file.pdf"],
        "document_dossiers": [{"dossier_id": "old-dos"}],
        "notes": [{"note_id": "old-note"}],
    }
    checkpointer = InMemoryCheckpointer(turn1_channels)

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    captured_inputs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, initial_input: Dict[str, Any], config: Any, version: str) -> Any:
            captured_inputs.append(initial_input)
            if False:
                yield {}

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_turn(
            agent_id="task-coordinator",
            prompt="Analyzing new document",
            thread_id="th-multi-turn-2",
            user_id="user-1",
            profile_id="profile-1",
            attachments=["new_file.pdf"],  # New attachment supplied
        ):
            pass

    assert len(captured_inputs) == 1
    inp = captured_inputs[0]
    assert inp["attachments"] == ["new_file.pdf"]
    assert inp["document_dossiers"] == []


# -------------------------------------------------------------------------
# 2. System Message Refresh on Routed Follow-Up
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_execution_node_refreshes_system_prompt_on_routing(tmp_path: Path) -> None:
    """AgentExecutionNode updates existing SystemMessage when routed specialist changes."""
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "trip-organizer")
    registry = AgentRegistry(agents_dir=agents_dir)

    captured_messages: List[Any] = []

    class FakeModel:
        async def ainvoke(self, msgs: List[Any], **kwargs: Any) -> Any:
            captured_messages.extend(msgs)
            return AIMessage(content="Specialist response")

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    node = AgentExecutionNode(registry=registry, model=FakeModel())

    state: AgentState = {
        "messages": [
            SystemMessage(content="Stale prompt from Turn 1 (budget-planner)"),
            HumanMessage(content="Follow-up question for Turn 2"),
        ],
        "current_agent": "trip-organizer",
    }

    await node.execute(state)

    assert len(captured_messages) == 2
    assert isinstance(captured_messages[0], SystemMessage)
    # Stale system prompt replaced by active specialist system prompt
    assert "trip-organizer" in captured_messages[0].content
    assert "Stale prompt from Turn 1" not in captured_messages[0].content


@pytest.mark.asyncio
async def test_agent_node_updates_first_message_with_new_system_prompt() -> None:
    """AgentNode replaces existing SystemMessage at index 0 with assembled prompt."""
    captured_messages: List[Any] = []

    class FakeModel:
        async def ainvoke(self, msgs: List[Any], **kwargs: Any) -> Any:
            captured_messages.extend(msgs)
            return AIMessage(content="Agent node answer")

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    node = AgentNode(model=FakeModel())
    # Mock assemble_system_prompt to return a distinct specialist prompt
    node.assemble_system_prompt = MagicMock(return_value="Refreshed System Prompt")  # type: ignore

    state: Dict[str, Any] = {
        "messages": [
            SystemMessage(content="Prior Turn System Prompt"),
            HumanMessage(content="Next Turn User Question"),
        ],
        "current_agent": "report-writer",
    }

    await node.execute(state)

    assert len(captured_messages) == 2
    assert isinstance(captured_messages[0], SystemMessage)
    assert captured_messages[0].content == "Refreshed System Prompt"


# -------------------------------------------------------------------------
# 3. Resume-Turn ToolContext
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_resume_turn_populates_tool_context(tmp_path: Path) -> None:
    """execute_resume_turn injects tool_context into graph_config configurable."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "task-coordinator")

    checkpointer = InMemoryCheckpointer({"is_tainted": False})

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    custom_context = ToolContext(
        user_id="user-resume",
        profile_id="profile-resume",
        principal="user",
        run_id="run-resume",
        workspace_root=tmp_path,
    )

    captured_configs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, cmd: Any, config: Any, version: str) -> Any:
            captured_configs.append(config)
            if False:
                yield {}

    app_record = MagicMock()
    app_record.status = "approved"
    app_record.args_dict = {"param": "val"}
    app_record.profile_id = "profile-resume"
    app_record.payload_hash = "h1"

    app_store = MagicMock()
    app_store.get = MagicMock(return_value=app_record)

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_resume_turn(
            thread_id="th-resume-1",
            approval_id="app-1",
            decision="approved",
            user_id="user-resume",
            profile_id="profile-resume",
            tool_context=custom_context,
            approval_store=app_store,
        ):
            pass

    assert len(captured_configs) == 1
    cfg = captured_configs[0]
    assert "configurable" in cfg
    assert "tool_context" in cfg["configurable"]
    assert cfg["configurable"]["tool_context"] is custom_context
    assert cfg["configurable"]["tool_context"].profile_id == "profile-resume"


@pytest.mark.asyncio
async def test_execute_resume_turn_constructs_default_tool_context_if_none_provided(tmp_path: Path) -> None:
    """execute_resume_turn builds valid ToolContext if not provided in kwargs."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "task-coordinator")

    checkpointer = InMemoryCheckpointer({"is_tainted": False})

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    captured_configs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, cmd: Any, config: Any, version: str) -> Any:
            captured_configs.append(config)
            if False:
                yield {}

    app_record = MagicMock()
    app_record.status = "approved"
    app_record.args_dict = {"param": "val"}
    app_record.profile_id = "profile-auto"
    app_record.payload_hash = "h1"

    app_store = MagicMock()
    app_store.get = MagicMock(return_value=app_record)

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_resume_turn(
            thread_id="th-resume-auto",
            approval_id="app-2",
            decision="approved",
            user_id="user-auto",
            profile_id="profile-auto",
            agent_id="task-coordinator",
            approval_store=app_store,
        ):
            pass

    assert len(captured_configs) == 1
    cfg = captured_configs[0]
    assert "tool_context" in cfg["configurable"]
    tc = cfg["configurable"]["tool_context"]
    assert isinstance(tc, ToolContext)
    assert tc.user_id == "user-auto"
    assert tc.profile_id == "profile-auto"


# -------------------------------------------------------------------------
# 4. Monotone TaintFlag Persistence Across Turns
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_node_sets_is_tainted_on_untrusted_output(tmp_path: Path) -> None:
    """ToolNode propagates taint to output state when UntrustedResult is returned."""
    untrusted_tool = ToolSpec(
        name="fetch_external_data",
        description="Fetches external untrusted records",
        executor=lambda args: UntrustedResult(data={"raw": "external payload"}),
        risk_tier="read",
    )

    tool_node = ToolNode(
        allowed_tools=["fetch_external_data"],
        tools=[untrusted_tool],
    )

    ctx = ToolContext(
        user_id="user-taint",
        profile_id="profile-taint",
        run_id="run-t",
        autonomy="A1",
        workspace_root=tmp_path,
    )

    state: Dict[str, Any] = {
        "tool_calls": [{"name": "fetch_external_data", "args": {}, "id": "call-1"}],
        "is_tainted": False,
        "thread_id": "th-taint-1",
    }

    config = {
        "configurable": {
            "tool_context": ctx,
            "thread_id": "th-taint-1",
        }
    }

    result = await tool_node.execute(state, config=config)

    assert result["is_tainted"] is True
    assert ctx.taint.is_tainted is True


@pytest.mark.asyncio
async def test_multi_turn_restores_monotone_taint_flag(tmp_path: Path) -> None:
    """Turn 2 restores TaintFlag(initial=True) if Turn 1 recorded is_tainted=True."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "audit-coordinator")

    tainted_channels = {
        "messages": [HumanMessage(content="Turn 1 query")],
        "is_tainted": True,
    }
    checkpointer = InMemoryCheckpointer(tainted_channels)

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    captured_inputs: List[Dict[str, Any]] = []
    captured_configs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, initial_input: Dict[str, Any], config: Any, version: str) -> Any:
            captured_inputs.append(initial_input)
            captured_configs.append(config)
            if False:
                yield {}

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_turn(
            agent_id="audit-coordinator",
            prompt="Turn 2 follow-up query",
            thread_id="th-taint-persist",
            user_id="user-1",
            profile_id="profile-1",
        ):
            pass

    assert len(captured_inputs) == 1
    inp = captured_inputs[0]
    assert inp["is_tainted"] is True

    cfg = captured_configs[0]
    tc = cfg["configurable"]["tool_context"]
    assert tc is not None
    assert tc.taint.is_tainted is True


@pytest.mark.asyncio
async def test_execute_resume_turn_restores_monotone_taint_flag(tmp_path: Path) -> None:
    """execute_resume_turn restores taint flag when checkpoint has is_tainted=True."""
    agents_dir = tmp_path / "agents"
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    _write_agent(agents_dir, "audit-coordinator")

    tainted_channels = {
        "is_tainted": True,
    }
    checkpointer = InMemoryCheckpointer(tainted_channels)

    service = AgentExecutionService(
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )

    captured_configs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, cmd: Any, config: Any, version: str) -> Any:
            captured_configs.append(config)
            if False:
                yield {}

    app_record = MagicMock()
    app_record.status = "approved"
    app_record.args_dict = {"param": "val"}
    app_record.profile_id = "profile-1"
    app_record.payload_hash = "h1"

    app_store = MagicMock()
    app_store.get = MagicMock(return_value=app_record)

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_resume_turn(
            thread_id="th-resume-taint",
            approval_id="app-taint",
            decision="approved",
            user_id="user-1",
            profile_id="profile-1",
            agent_id="audit-coordinator",
            approval_store=app_store,
        ):
            pass

    assert len(captured_configs) == 1
    cfg = captured_configs[0]
    tc = cfg["configurable"]["tool_context"]
    assert tc is not None
    assert tc.taint.is_tainted is True
