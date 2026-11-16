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

"""Unit and integration tests for live entity_changed SSE event emission (Issue #66)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from yarvelle_core.constants.api import SSE_ALL_EVENTS, SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.schemas.events import build_entity_changed_payload, EntityChangedPayload


def test_sse_event_entity_changed_constant():
    """Verify entity_changed constant and inclusion in SSE_ALL_EVENTS."""
    assert SSE_EVENT_ENTITY_CHANGED == "entity_changed"
    assert SSE_EVENT_ENTITY_CHANGED in SSE_ALL_EVENTS


def test_build_entity_changed_payload_create():
    """Test payload construction for create operations."""
    payload = build_entity_changed_payload(
        tool_name="create_workspace_note",
        args={"title": "Test Title", "content": "Body text"},
        output={"note_id": "note-abc-123", "slug": "test-title"},
        profile_id="p-42",
        scope="core",
    )

    assert payload["type"] == "entity_changed"
    assert payload["action"] == "created"
    assert payload["entity_type"] == "workspace_note"
    assert payload["entity"] == "workspace_note"
    assert payload["entity_id"] == "note-abc-123"
    assert payload["record_id"] == "note-abc-123"
    assert payload["profile_id"] == "p-42"
    assert payload["scope"] == "core"
    assert payload["tool"] == "create_workspace_note"
    assert "timestamp" in payload


def test_build_entity_changed_payload_update_and_delete():
    """Test payload construction for update and delete actions."""
    # Delete
    del_payload = build_entity_changed_payload(
        tool_name="delete_workspace_note",
        args={"note_id": "note-abc-123"},
        output={"success": True},
        profile_id="p-42",
        scope="core",
    )
    assert del_payload["action"] == "deleted"
    assert del_payload["entity_id"] == "note-abc-123"

    # Update
    upd_payload = build_entity_changed_payload(
        tool_name="update_workspace_note",
        args={"note_id": "note-abc-123", "title": "New Title"},
        output={"note_id": "note-abc-123"},
        profile_id="p-42",
        scope="core",
    )
    assert upd_payload["action"] == "updated"
    assert upd_payload["entity_id"] == "note-abc-123"


def test_build_entity_changed_payload_db_mutate():
    """Test payload derivation for generic database mutation tools."""
    payload = build_entity_changed_payload(
        tool_name="db_mutate_records",
        args={"table": "custom_records", "action": "insert", "values": {"name": "sample"}},
        output={"record": {"id": "rec-999"}},
        profile_id="p-1",
        scope="general",
    )
    assert payload["action"] == "created"
    assert payload["entity_type"] == "custom_records"
    assert payload["entity_id"] == "rec-999"
    assert payload["record_id"] == "rec-999"


def test_build_entity_changed_payload_entity_prefixed_tools():
    """Test entity_type and action extraction for <entity>_<verb> and <entity>_<verb>_scope tools."""
    c_payload = build_entity_changed_payload(
        tool_name="metrics_create",
        args={"value": 42},
        output={"id": "m-1"},
        profile_id="p-1",
    )
    assert c_payload["entity_type"] == "metrics"
    assert c_payload["entity"] == "metrics"
    assert c_payload["action"] == "created"

    d_payload = build_entity_changed_payload(
        tool_name="notes_delete_workspace",
        args={"slug": "daily-plan"},
        output={"ok": True},
        profile_id="p-1",
    )
    assert d_payload["entity_type"] == "notes"
    assert d_payload["action"] == "deleted"


@pytest.mark.asyncio
async def test_tool_node_dispatches_entity_changed_on_mutating_tool():
    """ToolNode should dispatch entity_changed when a mutating tool succeeds."""
    from yarvelle_core.workflows.nodes.tool_node import ToolNode
    from yarvelle_core.engine.tool_registry import ToolSpec
    from yarvelle_core.schemas.tool import ToolResult
    from langchain_core.messages import AIMessage

    mutating_spec = ToolSpec(
        name="create_workspace_note",
        description="Creates a note",
        risk_tier="write_local",
        executor=AsyncMock(return_value=ToolResult(success=True, output={"note_id": "n-1"})),
    )

    node = ToolNode(tools=[mutating_spec])
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "create_workspace_note", "args": {"title": "Hello"}, "id": "call_1"}],
            )
        ],
        "profile_id": "prof-test",
        "user_id": "user-test",
        "scope": "core",
    }

    dispatched = []

    async def fake_dispatch(event_name, event_data):
        dispatched.append((event_name, event_data))

    with patch("yarvelle_core.engine.tool_exec.execute_tool_call") as mock_exec, \
         patch("yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event", new=fake_dispatch):
        mock_exec.return_value = ToolResult(success=True, output={"note_id": "n-1"})
        res = await node.execute(state)
        assert res["messages"]

    # Verify entity_changed event was dispatched
    events = [d for d in dispatched if d[0] == SSE_EVENT_ENTITY_CHANGED]
    assert len(events) == 1
    ev_name, ev_payload = events[0]
    assert ev_name == "entity_changed"
    assert ev_payload["tool"] == "create_workspace_note"
    assert ev_payload["action"] == "created"
    assert ev_payload["entity_id"] == "n-1"


@pytest.mark.asyncio
async def test_tool_node_does_not_dispatch_on_read_tool():
    """ToolNode should NOT dispatch entity_changed on read-only tools."""
    from yarvelle_core.workflows.nodes.tool_node import ToolNode
    from yarvelle_core.engine.tool_registry import ToolSpec
    from yarvelle_core.schemas.tool import ToolResult
    from langchain_core.messages import AIMessage

    read_spec = ToolSpec(
        name="attach-read",
        description="Reads attachment",
        risk_tier="read",
    )

    node = ToolNode(tools=[read_spec])
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "attach-read", "args": {"filename": "test.txt"}, "id": "call_2"}],
            )
        ],
        "profile_id": "prof-test",
        "user_id": "user-test",
    }

    dispatched = []

    async def fake_dispatch(event_name, event_data):
        dispatched.append((event_name, event_data))

    with patch("yarvelle_core.engine.tool_exec.execute_tool_call") as mock_exec, \
         patch("yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event", new=fake_dispatch):
        mock_exec.return_value = ToolResult(success=True, output={"content": "sample content"})
        await node.execute(state)

    events = [d for d in dispatched if d[0] == SSE_EVENT_ENTITY_CHANGED]
    assert len(events) == 0


@pytest.mark.asyncio
async def test_service_execute_turn_yields_entity_changed():
    """AgentExecutionService should yield entity_changed custom events during execute_turn."""
    from yarvelle_core.engine.service import AgentExecutionService

    async def fake_stream(*args, **kwargs):
        yield {
            "event": "on_custom_event",
            "name": SSE_EVENT_ENTITY_CHANGED,
            "data": {
                "type": "entity_changed",
                "entity_type": "sample_record",
                "entity": "sample_record",
                "entity_id": "rec-123",
                "record_id": "rec-123",
                "action": "created",
                "profile_id": "p-1",
                "scope": "core",
                "tool": "create_sample_record",
                "timestamp": "2026-11-16T03:00:00Z",
            },
        }

    mock_app = MagicMock()
    mock_app.astream_events = fake_stream

    service = AgentExecutionService(graph=mock_app, safety_policy=None, default_agent_id="orchestrator")
    events = []
    async for ev in service.execute_turn(
        thread_id="t-1",
        prompt="test prompt",
        profile_id="p-1",
    ):
        events.append(ev)

    entity_events = [e for e in events if e.get("type") == "entity_changed"]
    assert len(entity_events) == 1
    assert entity_events[0]["entity_id"] == "rec-123"
    assert entity_events[0]["action"] == "created"


@pytest.mark.asyncio
async def test_service_execute_resume_turn_yields_entity_changed():
    """AgentExecutionService should yield entity_changed custom events during execute_resume_turn."""
    from yarvelle_core.engine.service import AgentExecutionService

    async def fake_stream(*args, **kwargs):
        yield {
            "event": "on_custom_event",
            "name": SSE_EVENT_ENTITY_CHANGED,
            "data": {
                "type": "entity_changed",
                "entity_type": "sample_record",
                "entity": "sample_record",
                "entity_id": "rec-456",
                "record_id": "rec-456",
                "action": "updated",
                "profile_id": "p-1",
                "scope": "core",
                "tool": "update_sample_record",
                "timestamp": "2026-11-16T03:00:00Z",
            },
        }

    mock_app = MagicMock()
    mock_app.astream_events = fake_stream

    mock_store = MagicMock()
    mock_rec = MagicMock()
    mock_rec.status = "approved"
    mock_rec.args = {}
    mock_rec.profile_id = "p-1"
    mock_rec.payload_hash = "abc"
    mock_store.get.return_value = mock_rec

    service = AgentExecutionService(graph=mock_app, safety_policy=None, default_agent_id="orchestrator")
    events = []
    async for ev in service.execute_resume_turn(
        thread_id="t-1",
        approval_id="app-1",
        decision="approved",
        approval_store=mock_store,
    ):
        events.append(ev)

    entity_events = [e for e in events if e.get("type") == "entity_changed"]
    assert len(entity_events) == 1
    assert entity_events[0]["entity_id"] == "rec-456"
    assert entity_events[0]["action"] == "updated"


@pytest.mark.asyncio
async def test_main_agent_node_subagent_mutating_tool_dispatches_entity_changed():
    """MainAgentNode resolver should dispatch entity_changed when a subagent mutating tool succeeds."""
    from yarvelle_core.workflows.nodes.main_agent_node import MainAgentNode
    from yarvelle_core.engine.tool_registry import ToolSpec, ToolSpecRegistry
    from yarvelle_core.schemas.tool import ToolResult

    dispatched = []

    async def fake_dispatch(event_name, event_data):
        dispatched.append((event_name, event_data))

    reg = ToolSpecRegistry()
    mutating_spec = ToolSpec(
        name="custom_mutate_item",
        description="Mutates an item",
        risk_tier="write_local",
        executor=AsyncMock(return_value=ToolResult(success=True, output={"id": "item-101", "action": "created"})),
    )
    reg.register(mutating_spec, pack_id="core")

    mock_router = MagicMock()
    mock_router.registry.get.return_value = None
    mock_router.tool_resolver = None

    node = MainAgentNode.__new__(MainAgentNode)
    node.router = mock_router
    node.tool_registry = reg

    state = {
        "profile_id": "p-test",
        "user_id": "u-test",
        "thread_id": "th-1",
        "autonomy": "A1",
        "scope": "core",
    }

    resolver = node._build_turn_tool_resolver(state)
    tools = resolver("agent-1", ["custom_mutate_item"])
    assert len(tools) == 1

    with patch("langchain_core.callbacks.manager.adispatch_custom_event", new=fake_dispatch):
        res = await tools[0].ainvoke({"id": "item-101"})
        assert res

    entity_events = [d for d in dispatched if d[0] == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) == 1
    assert entity_events[0][1]["tool"] == "custom_mutate_item"
    assert entity_events[0][1]["entity_id"] == "item-101"


