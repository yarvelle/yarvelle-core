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

"""Tier 3 E2E Cross-Feature Interactions & Live SSE Invalidation Tests.

Tests mutating tool executions triggering domain-neutral `entity_changed` SSE event
emission, payload validation, read-tool suppression, and SSE streaming forwarding:
- Mutating tool execution -> SSE `entity_changed` event emission and subscription
- Cross-feature pairwise interactions between ToolNode, MainAgentNode, and Service
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.constants.api import SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.db.models import Note, Profile, User
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.engine.tool_registry import create_default_registry
from yarvelle_core.schemas.events import EntityChangedPayload, build_entity_changed_payload
from yarvelle_core.scope.context import DEFAULT_SCOPE, scope_context
from yarvelle_core.workflows.nodes.tool_node import ToolNode


@pytest.mark.asyncio
async def test_interaction_create_workspace_note_emits_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """create_workspace_note tool execution inside ToolNode emits entity_changed (created)."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()
    state: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "call-create-note-1",
                "name": "create_workspace_note",
                "args": {
                    "note_title": "Interactions Test Note",
                    "note_content": "Content verified across boundaries.",
                    "slug": "interactions-test-note",
                },
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res = await tool_node.execute(state)

    assert len(res["tool_messages"]) == 1
    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) == 1
    event = entity_events[0]

    model = EntityChangedPayload(**event)
    assert model.type == SSE_EVENT_ENTITY_CHANGED
    assert model.action in ("created", "updated")
    assert model.profile_id == profile.id
    assert model.scope == DEFAULT_SCOPE
    assert model.tool == "create_workspace_note"


@pytest.mark.asyncio
async def test_interaction_update_workspace_note_emits_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """update_workspace_note tool execution inside ToolNode emits entity_changed (updated)."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()

    # Seed existing note in DB
    note_id = str(uuid.uuid4())
    async with e2e_db_factory() as session:
        existing_note = Note(
            id=note_id,
            profile_id=profile.id,
            user_id=_user.id,
            slug="pre-existing-note",
            title="Pre-existing Note",
            content="Initial text.",
            type="scratchpad",
            scope=DEFAULT_SCOPE,
        )
        session.add(existing_note)
        await session.commit()

    state: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "call-update-note-1",
                "name": "update_workspace_note",
                "args": {
                    "id": note_id,
                    "content": "Updated body text for live invalidation.",
                },
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res = await tool_node.execute(state)

    assert len(res["tool_messages"]) == 1
    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) >= 1
    event = entity_events[-1]
    assert event["action"] == "updated"
    assert event["entity_id"] == note_id


@pytest.mark.asyncio
async def test_interaction_delete_workspace_note_emits_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """delete_workspace_note tool execution inside ToolNode emits entity_changed (deleted)."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()

    # Seed existing note in DB
    note_id = str(uuid.uuid4())
    async with e2e_db_factory() as session:
        session.add(
            Note(
                id=note_id,
                profile_id=profile.id,
                user_id=_user.id,
                slug="to-be-deleted",
                title="To Be Deleted",
                content="Temporary content.",
                type="scratchpad",
                scope=DEFAULT_SCOPE,
            )
        )
        await session.commit()

    state: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "call-delete-note-1",
                "name": "delete_workspace_note",
                "args": {"id": note_id},
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res = await tool_node.execute(state)

    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) >= 1
    event = entity_events[-1]
    assert event["action"] == "deleted"
    assert event["entity_id"] == note_id


@pytest.mark.asyncio
async def test_interaction_workspace_note_write_emits_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    monkeypatch: pytest.MonkeyPatch,
):
    """workspace-note tool execution inside ToolNode emits entity_changed (created/updated)."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()

    state: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "call-ws-note-1",
                "name": "workspace-note",
                "args": {
                    "action": "write",
                    "title": "Steward Operations Note",
                    "content": "Verified workspace note body.",
                },
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res = await tool_node.execute(state)

    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) >= 1
    event = entity_events[-1]
    assert event["type"] == SSE_EVENT_ENTITY_CHANGED
    assert event["action"] in ("created", "updated")
    assert event["profile_id"] == profile.id


@pytest.mark.asyncio
async def test_interaction_read_tools_never_emit_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    monkeypatch: pytest.MonkeyPatch,
):
    """Read tools (list_workspace_notes, get_workspace_note, attach-read) never emit entity_changed."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()

    read_calls = [
        {"id": "c1", "name": "list_workspace_notes", "args": {}},
        {"id": "c2", "name": "get_workspace_note", "args": {"id": "non-existent"}},
        {"id": "c3", "name": "list_profile_reminders", "args": {}},
    ]

    for call in read_calls:
        state: Dict[str, Any] = {
            "profile_id": profile.id,
            "user_id": _user.id,
            "workspace_root": str(e2e_workspace),
            "tool_calls": [call],
        }
        with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
            await tool_node.execute(state)

    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) == 0


@pytest.mark.asyncio
async def test_interaction_profile_and_scope_isolation_in_entity_changed():
    """Entity changed payloads preserve profile_id and scope isolation."""
    payload_a = build_entity_changed_payload(
        tool_name="create_workspace_note",
        args={"title": "Profile A Task"},
        output={"id": "rec-a", "action": "created"},
        profile_id="profile-alpha",
        scope="steward.internal",
    )
    payload_b = build_entity_changed_payload(
        tool_name="create_workspace_note",
        args={"title": "Profile B Task"},
        output={"id": "rec-b", "action": "created"},
        profile_id="profile-beta",
        scope="steward.external",
    )

    assert payload_a["profile_id"] == "profile-alpha"
    assert payload_a["scope"] == "steward.internal"
    assert payload_b["profile_id"] == "profile-beta"
    assert payload_b["scope"] == "steward.external"
    assert payload_a["profile_id"] != payload_b["profile_id"]
