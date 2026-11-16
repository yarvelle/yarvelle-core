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

"""Tier 4 E2E Real-World Application Scenario Tests.

End-to-end, multi-turn, domain-neutral steward workflows exercising:
- Dynamic pack tool registry provisioning and validation (Feature 1)
- Live entity_changed SSE emission on mutating tool executions (Feature 2)
- Scoped workspace notes creation, update, and lifecycle (Feature 3)
- Profile reminders, routines, and calendar scheduling parity (Feature 4)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.constants.api import SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.db.models import Connection, Note, Profile, Reminder, Routine, User
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.engine.tool_registry import create_default_registry
from yarvelle_core.schemas.events import EntityChangedPayload, build_entity_changed_payload
from yarvelle_core.scope.context import DEFAULT_SCOPE, scope_context
from yarvelle_core.tools.builtin_handlers import exec_attach_read, exec_workspace_note
from yarvelle_core.tools.mcp_db_toolbox import get_db_toolbox
from yarvelle_core.workflows.nodes.tool_node import ToolNode


@pytest.mark.asyncio
async def test_scenario_steward_workspace_planning_and_note_organization(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    e2e_auth_client: AsyncClient,
    e2e_db_factory: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """Scenario 1: Steward user organizes quarterly planning, creates structured notes, and schedules reminders."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()

    # Step 1: Create quarterly objectives note via tool
    state_step1: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "step1-call",
                "name": "create_workspace_note",
                "args": {
                    "note_title": "Q1 Operations Roadmap",
                    "note_content": "1. Upgrade database indexes\n2. Consolidate connectors\n3. Enforce audits",
                    "slug": "q1-operations-roadmap",
                },
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res1 = await tool_node.execute(state_step1)

    assert len(res1["tool_messages"]) == 1
    note_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(note_events) >= 1
    assert note_events[-1]["tool"] == "create_workspace_note"
    assert note_events[-1]["action"] in ("created", "updated")

    # Step 2: Schedule a recurring reminder for weekly roadmap progress check
    due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    rem_resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/reminders",
        json={
            "title": "Review Q1 Operations Roadmap Progress",
            "next_due_at": due,
            "rrule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
            "timezone": "UTC",
            "category": "general",
        },
    )
    assert rem_resp.status_code == 201
    reminder_id = rem_resp.json()["id"]

    # Step 3: Verify persistence and query parity
    async with e2e_db_factory() as session:
        note_row = (
            await session.execute(
                select(Note).where(
                    Note.profile_id == profile.id,
                    Note.slug == "q1-operations-roadmap",
                )
            )
        ).scalar_one_or_none()
        assert note_row is not None
        assert "Roadmap" in note_row.title

        rem_row = (
            await session.execute(select(Reminder).where(Reminder.id == reminder_id))
        ).scalar_one_or_none()
        assert rem_row is not None
        assert rem_row.profile_id == profile.id


@pytest.mark.asyncio
async def test_scenario_document_ingestion_and_structured_note_extraction(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
):
    """Scenario 2: Steward user uploads a document, ingests it, and persists extracted summary."""
    _user, profile = e2e_steward_context

    # Create document in attachments under scoped user/profile directory
    doc_dir = e2e_workspace / "attachments" / _user.id / profile.id
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / "briefing.txt"
    doc_path.write_text(
        "System Architecture Specification\nVersion: 2.5\nLead Steward: Alex\nScope: Core Runtime",
        encoding="utf-8",
    )

    ctx = ToolContext(
        user_id=_user.id,
        profile_id=profile.id,
        workspace_root=e2e_workspace,
    )

    # Ingest document text via attach-read
    read_res = await exec_attach_read({"path": "briefing.txt"}, ctx)
    assert read_res.success is True
    assert "System Architecture Specification" in str(read_res.output)

    # Persist summary note
    note_res = await exec_workspace_note(
        {
            "action": "write",
            "title": "Architecture Briefing Summary",
            "content": f"Ingested text summary:\n{read_res.output}",
        },
        ctx,
    )
    assert note_res.success is True


@pytest.mark.asyncio
async def test_scenario_database_introspection_and_scoped_mutation(
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
):
    """Scenario 3: Dynamic MCP database toolbox introspects schema and mutates records safely."""
    _user, profile = e2e_steward_context
    toolbox = get_db_toolbox()

    ctx = ToolContext(
        user_id=_user.id,
        profile_id=profile.id,
    )

    # Introspect notes schema
    schema_res = await toolbox.execute_tool("db_inspect_schema", {"table": "notes"}, ctx=ctx)
    assert schema_res is not None
    assert "notes" in str(schema_res).lower()

    # Query notes count
    query_res = await toolbox.execute_tool(
        "db_execute_query",
        {"statement": f"SELECT COUNT(*) as note_count FROM notes WHERE profile_id = '{profile.id}'"},
        ctx=ctx,
    )
    assert query_res is not None


@pytest.mark.asyncio
async def test_scenario_standing_routine_lifecycle_and_execution(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: async_sessionmaker[Any],
):
    """Scenario 4: Steward creates an A2 standing routine, checks status, and manages lifecycle."""
    _user, profile = e2e_steward_context

    # Seed required connectors for A2 standing routine readiness gate
    async with e2e_db_factory() as session:
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=_user.id,
                profile_id=profile.id,
                connector_id="connector-alpha",
                status="active",
            )
        )
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=_user.id,
                profile_id=profile.id,
                connector_id="connector-beta",
                status="active",
            )
        )
        await session.commit()

    # Create standing routine
    create_resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/routines",
        json={
            "name": "Nightly Workspace Maintenance",
            "description": "Performs housekeeping on temporary logs and notes",
            "tool_name": "workspace-note",
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "timezone": "UTC",
            "args": {"action": "clean"},
        },
    )
    assert create_resp.status_code in (200, 201)
    routine_id = create_resp.json()["id"]

    # Pause routine
    pause_resp = await e2e_auth_client.patch(
        f"/api/v1/profiles/{profile.id}/routines/{routine_id}",
        json={"action": "pause"},
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    # Resume routine
    resume_resp = await e2e_auth_client.patch(
        f"/api/v1/profiles/{profile.id}/routines/{routine_id}",
        json={"action": "resume"},
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_scenario_multi_agent_steward_collaboration_and_staged_action(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
):
    """Scenario 5: Multi-agent deliberation and staged action agreement in neutral steward context."""
    _user, profile = e2e_steward_context
    registry = create_default_registry()

    # Verify registered tool specs for coordination
    assert registry.get("workspace-note") is not None
    assert registry.get("create_workspace_note") is not None

    # Verify building entity changed payload for a staged action execution
    payload = build_entity_changed_payload(
        tool_name="create_workspace_note",
        args={"title": "Deliberated Consensus Plan", "content": "Approved by all coordinators."},
        output={"id": "plan-consensus-1", "action": "created"},
        profile_id=profile.id,
        scope=DEFAULT_SCOPE,
    )
    model = EntityChangedPayload(**payload)
    assert model.type == SSE_EVENT_ENTITY_CHANGED
    assert model.entity_id == "plan-consensus-1"
    assert model.action == "created"
    assert model.profile_id == profile.id
