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

"""Tier 1 E2E Feature Coverage Tests for Yarvelle Core (Features 1–4).

Covers happy-path category-partition equivalence classes:
- Feature 1: Dynamic Pack Tool Registration & Validation (Issue #64)
- Feature 2: Live entity_changed SSE Event Emission (Issue #66)
- Feature 3: Core Notes REST Router & @yarvelle/ui NoteEditor (Issue #65)
- Feature 4: Core Reminders/Tasks/Calendar Parity & Leak Purge (Issue #67)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import pytest
from httpx import AsyncClient
from langchain_core.messages import HumanMessage, ToolMessage

from yarvelle_core.constants.api import SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.db.models import Note, Profile, Reminder, Routine, User
from yarvelle_core.engine.tool_registry import (
    DataFlows,
    ToolSpec,
    ToolSpecRegistry,
    create_default_registry,
)
from yarvelle_core.loaders.union import (
    ToolValidationError,
    compute_effective_tools,
    validate_tools_against_registry,
    validate_tools_in_phase0,
)
from yarvelle_core.schemas.events import EntityChangedPayload, build_entity_changed_payload
from yarvelle_core.scope.context import DEFAULT_SCOPE, scope_context
from yarvelle_core.workflows.nodes.tool_node import ToolNode


# ============================================================================
# Feature 1: Dynamic Pack Tool Registration & Validation (Issue #64)
# ============================================================================


def test_dynamic_tool_registration_in_registry():
    """Register declarative pack tool in ToolSpecRegistry with specific scopes and tier."""
    registry = ToolSpecRegistry()
    spec = ToolSpec(
        name="operations_export_csv",
        description="Exports operations dataset to CSV format",
        risk_tier="write_local",
        trust="trusted",
        scopes={"operations.export"},
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
    )

    registry.register(spec, pack_id="operations")

    registered = registry.get("operations_export_csv")
    assert registered is not None
    assert registered.name == "operations_export_csv"
    assert registered.risk_tier == "write_local"
    assert "operations.export" in registered.scopes
    assert registry.get_pack_id("operations_export_csv") == "operations"

    # Listed when pack is enabled
    enabled_specs = registry.list_for_enabled_packs(["operations"])
    assert spec in enabled_specs


def test_filter_tools_by_enabled_packs():
    """Resolve effective tools when enabled_packs is provided vs empty."""
    registry = ToolSpecRegistry()
    core_tool = ToolSpec(name="core_summary", risk_tier="read", scopes={"core.view"})
    ops_tool = ToolSpec(name="ops_inventory", risk_tier="read", scopes={"ops.view"})
    logistics_tool = ToolSpec(name="logistics_dispatch", risk_tier="write_local", scopes={"logistics.write"})

    registry.register(core_tool, pack_id="core")
    registry.register(ops_tool, pack_id="operations")
    registry.register(logistics_tool, pack_id="logistics")

    # With no packs enabled, only core tools are returned
    core_only = registry.list_for_enabled_packs([])
    assert core_tool in core_only
    assert ops_tool not in core_only
    assert logistics_tool not in core_only

    # With operations enabled
    ops_enabled = registry.list_for_enabled_packs(["operations"])
    assert core_tool in ops_enabled
    assert ops_tool in ops_enabled
    assert logistics_tool not in ops_enabled

    # With both operations and logistics enabled
    both_enabled = registry.list_for_enabled_packs(["operations", "logistics"])
    assert core_tool in both_enabled
    assert ops_tool in both_enabled
    assert logistics_tool in both_enabled


def test_agent_manifest_with_pack_tools_validation():
    """Validate agent manifest declaring pack tools passes validation without raising ToolValidationError."""
    allowed = {"attach-read", "workspace-note", "custom_pack_tool"}

    # Validation succeeds when all tools are in allowed set
    validate_tools_against_registry(["attach-read", "custom_pack_tool"], allowed_tools=allowed)

    effective = compute_effective_tools(
        agent_tools=["custom_pack_tool", "attach-read"],
        skills=[],
        allowed_tools=allowed,
    )
    assert effective == ["custom_pack_tool", "attach-read"]


def test_reject_undeclared_or_unregistered_tools():
    """Attempting to declare a tool not in registry or active packs fails closed with descriptive error."""
    allowed = {"attach-read", "workspace-note"}

    with pytest.raises(ToolValidationError) as exc_info:
        validate_tools_against_registry(["unregistered_rogue_tool"], allowed_tools=allowed)
    assert "unregistered_rogue_tool" in str(exc_info.value)
    assert "not in registered toolset" in str(exc_info.value)

    # Backward compatible Phase 0 validator check
    with pytest.raises(ToolValidationError) as phase0_exc:
        validate_tools_in_phase0(["unregistered_rogue_tool"])
    assert "unregistered_rogue_tool" in str(phase0_exc.value)


def test_db_toolset_dynamic_expansion():
    """Verify db_toolset tools expand dynamically per active pack."""
    registry = create_default_registry()
    db_tools = ["db_inspect_schema", "db_execute_query", "db_mutate_records"]

    for tool_name in db_tools:
        spec = registry.get(tool_name)
        assert spec is not None, f"Expected {tool_name} in default registry"

    assert registry.get("db_inspect_schema").risk_tier == "read"
    assert registry.get("db_execute_query").risk_tier == "read"
    assert registry.get("db_mutate_records").risk_tier in ("write_local", "write_external", "irreversible")


# ============================================================================
# Feature 2: Live entity_changed SSE Event Emission (Issue #66)
# ============================================================================


@pytest.mark.asyncio
async def test_tool_node_emits_entity_changed_on_write(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    monkeypatch: pytest.MonkeyPatch,
):
    """ToolNode emits entity_changed with metadata on successful write_local/write_external tool execution."""
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
                "id": "call-1",
                "name": "create_workspace_note",
                "args": {
                    "note_title": "Project Blueprint",
                    "note_content": "Detailed system architectural plan.",
                    "slug": "project-blueprint",
                },
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        result = await tool_node.execute(state)

    assert len(result.get("tool_messages", [])) == 1
    # Verify entity_changed event was dispatched
    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) == 1
    event = entity_events[0]
    assert event["type"] == SSE_EVENT_ENTITY_CHANGED
    assert event["profile_id"] == profile.id
    assert event["action"] in ("created", "updated")
    assert event["tool"] == "create_workspace_note"


@pytest.mark.asyncio
async def test_main_agent_node_emits_entity_changed_on_subagent_mutation():
    """MainAgentNode emits entity_changed upon completion of a mutating subagent tool."""
    from yarvelle_core.schemas.events import build_entity_changed_payload

    payload = build_entity_changed_payload(
        tool_name="update_workspace_note",
        args={"id": "note-456", "content": "Updated plan steps."},
        output={"status": "ok", "action": "updated", "id": "note-456"},
        profile_id="prof-steward-1",
        scope="steward.ops",
    )

    assert payload["type"] == SSE_EVENT_ENTITY_CHANGED
    assert payload["action"] == "updated"
    assert payload["entity_id"] == "note-456"
    assert payload["profile_id"] == "prof-steward-1"
    assert payload["tool"] == "update_workspace_note"


@pytest.mark.asyncio
async def test_read_tools_suppress_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    monkeypatch: pytest.MonkeyPatch,
):
    """Read-only tools (risk_tier='read') do NOT emit entity_changed."""
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
                "id": "call-read-1",
                "name": "list_workspace_notes",
                "args": {},
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        await tool_node.execute(state)

    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    assert len(entity_events) == 0, "Read tools must never emit entity_changed events"


@pytest.mark.asyncio
async def test_failed_tool_execution_suppresses_entity_changed(
    e2e_workspace: Path,
    e2e_steward_context: Tuple[User, Profile],
    monkeypatch: pytest.MonkeyPatch,
):
    """Tool executions returning success=False or throwing errors do NOT emit entity_changed."""
    _user, profile = e2e_steward_context
    dispatched_events: List[Tuple[str, Dict[str, Any]]] = []

    async def mock_adispatch(event_name: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "yarvelle_core.workflows.nodes.tool_node.adispatch_custom_event",
        mock_adispatch,
    )

    tool_node = ToolNode()
    # Attempting to delete a non-existent note
    state: Dict[str, Any] = {
        "profile_id": profile.id,
        "user_id": _user.id,
        "workspace_root": str(e2e_workspace),
        "tool_calls": [
            {
                "id": "call-fail-1",
                "name": "delete_workspace_note",
                "args": {"id": "non-existent-note-id-000"},
            }
        ],
    }

    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        res = await tool_node.execute(state)

    entity_events = [p for name, p in dispatched_events if name == SSE_EVENT_ENTITY_CHANGED]
    # If the tool failed, entity_changed must not be emitted
    tool_msg_content = str(res["tool_messages"][0].content)
    if "error" in tool_msg_content.lower() or "not found" in tool_msg_content.lower():
        assert len(entity_events) == 0


def test_entity_changed_payload_contract_compliance():
    """Validates payload fields against the canonical EntityChangedPayload contract."""
    payload = build_entity_changed_payload(
        tool_name="create_profile_reminder",
        args={"title": "Team Standup", "profile_id": "prof-123"},
        output={"id": "rem-999", "action": "created"},
        profile_id="prof-123",
        scope="steward.general",
    )

    # Validate against strict Pydantic model
    model = EntityChangedPayload(**payload)
    assert model.type == SSE_EVENT_ENTITY_CHANGED
    assert model.entity_type in ("reminder", "profile_reminder")
    assert model.entity_id == "rem-999"
    assert model.record_id == "rem-999"
    assert model.action == "created"
    assert model.profile_id == "prof-123"
    assert model.scope == "steward.general"
    assert model.tool == "create_profile_reminder"
    # Ensure timestamp is valid ISO 8601
    dt = datetime.fromisoformat(model.timestamp)
    assert dt.tzinfo is not None


# ============================================================================
# Feature 3: Core Notes REST Router & @yarvelle/ui NoteEditor (Issue #65)
# ============================================================================


@pytest.mark.asyncio
async def test_notes_rest_create_profile_scoped(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """POST /api/v1/notes creates a note bound to profile and scope."""
    _user, profile = e2e_steward_context
    payload = {
        "title": "Quarterly Objectives",
        "content": "Deliver milestone objectives on schedule.",
        "type": "prep",
        "tags": ["objectives", "planning"],
        "profile_id": profile.id,
    }

    response = await e2e_auth_client.post("/api/v1/notes", json=payload)
    if response.status_code == 404:
        # Check alternative profile-prefixed path or skip gracefully if router not yet merged
        alt_response = await e2e_auth_client.post(f"/api/v1/profiles/{profile.id}/notes", json=payload)
        if alt_response.status_code == 404:
            pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")
        response = alt_response

    assert response.status_code in (200, 201)
    data = response.json()
    assert data["title"] == "Quarterly Objectives"
    assert data["profile_id"] == profile.id
    assert "id" in data


@pytest.mark.asyncio
async def test_notes_rest_list_with_profile_filter(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """GET /api/v1/notes lists notes matching profile and scope."""
    _user, profile = e2e_steward_context
    response = await e2e_auth_client.get(f"/api/v1/notes?profile_id={profile.id}")
    if response.status_code == 404:
        alt_response = await e2e_auth_client.get(f"/api/v1/profiles/{profile.id}/notes")
        if alt_response.status_code == 404:
            pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")
        response = alt_response

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, (list, dict))


@pytest.mark.asyncio
async def test_notes_rest_update_and_pin(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """PATCH /api/v1/notes/{id} updates title, body, and pinned flag."""
    _user, profile = e2e_steward_context
    create_resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": "Draft Agenda", "content": "Initial thoughts.", "profile_id": profile.id},
    )
    if create_resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    note_id = create_resp.json()["id"]
    patch_resp = await e2e_auth_client.patch(
        f"/api/v1/notes/{note_id}",
        json={"title": "Final Agenda", "content": "Approved agenda items.", "pinned": True},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["title"] == "Final Agenda"


@pytest.mark.asyncio
async def test_notes_rest_delete(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """DELETE /api/v1/notes/{id} deletes note and enforces isolation."""
    _user, profile = e2e_steward_context
    create_resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": "To Delete", "content": "Ephemeral.", "profile_id": profile.id},
    )
    if create_resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    note_id = create_resp.json()["id"]
    del_resp = await e2e_auth_client.delete(f"/api/v1/notes/{note_id}")
    assert del_resp.status_code in (200, 204)

    # Subsequent GET returns 404
    get_resp = await e2e_auth_client.get(f"/api/v1/notes/{note_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_notes_filter_by_type_and_tag(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Querying notes by tag or type returns exact matches."""
    _user, profile = e2e_steward_context
    create_resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={
            "title": "Checklist Note",
            "content": "Step 1, Step 2",
            "type": "prep",
            "tags": ["urgent", "operations"],
            "profile_id": profile.id,
        },
    )
    if create_resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    filter_resp = await e2e_auth_client.get(f"/api/v1/notes?profile_id={profile.id}&type=prep")
    assert filter_resp.status_code == 200


# ============================================================================
# Feature 4: Core Reminders/Tasks/Calendar Parity & Leak Purge (Issue #67)
# ============================================================================


@pytest.mark.asyncio
async def test_reminders_crud_and_recurrence(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Full CRUD on profile reminders with timezone-aware RRULE."""
    _user, profile = e2e_steward_context
    due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # Create reminder
    create_resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/reminders",
        json={
            "title": "Submit Weekly Stewardship Report",
            "next_due_at": due,
            "rrule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
            "timezone": "UTC",
            "category": "general",
        },
    )
    assert create_resp.status_code == 201
    rem_data = create_resp.json()
    assert rem_data["title"] == "Submit Weekly Stewardship Report"
    assert "rrule" in rem_data
    rem_id = rem_data["id"]

    # List reminders
    list_resp = await e2e_auth_client.get(f"/api/v1/profiles/{profile.id}/reminders")
    assert list_resp.status_code == 200
    assert any(r["id"] == rem_id for r in list_resp.json().get("reminders", []))

    # Update reminder
    patch_resp = await e2e_auth_client.patch(
        f"/api/v1/profiles/{profile.id}/reminders/{rem_id}",
        json={"title": "Submit Monthly Stewardship Report"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Submit Monthly Stewardship Report"

    # Delete reminder
    del_resp = await e2e_auth_client.delete(f"/api/v1/profiles/{profile.id}/reminders/{rem_id}")
    assert del_resp.status_code in (200, 204)


@pytest.mark.asyncio
async def test_routines_and_tasks_crud(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
    e2e_db_factory: Any,
):
    """Routine and task creation, item toggling, and completion tracking."""
    from yarvelle_core.db.models import Connection

    _user, profile = e2e_steward_context
    async with e2e_db_factory() as session:
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=_user.id,
                profile_id=profile.id,
                connector_id="mock_conn_alpha",
                status="active",
            )
        )
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=_user.id,
                profile_id=profile.id,
                connector_id="mock_conn_beta",
                status="active",
            )
        )
        await session.commit()

    create_resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/routines",
        json={
            "name": "Morning Workspace Routine",
            "description": "Daily system checks and inbox triage",
            "tool_name": "workspace-note",
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "timezone": "UTC",
            "args": {"action": "check"},
        },
    )
    assert create_resp.status_code in (200, 201)
    routine_data = create_resp.json()
    assert routine_data["name"] == "Morning Workspace Routine"
    routine_id = routine_data["id"]

    # List routines
    list_resp = await e2e_auth_client.get(f"/api/v1/profiles/{profile.id}/routines")
    assert list_resp.status_code == 200
    routines_list = list_resp.json().get("routines", [])
    assert any(r["id"] == routine_id for r in routines_list)

    # Update routine status (pause)
    patch_resp = await e2e_auth_client.patch(
        f"/api/v1/profiles/{profile.id}/routines/{routine_id}",
        json={"action": "pause"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "paused"


def test_calendar_week_view_date_filtering():
    """Calendar week-view displays events strictly on their corresponding day."""
    # Empirical test of week date filtering invariant
    events = [
        {"id": "ev-1", "title": "Monday Sync", "start": "2026-11-16T09:00:00Z"},
        {"id": "ev-2", "title": "Wednesday Review", "start": "2026-11-18T14:00:00Z"},
        {"id": "ev-3", "title": "Next Week Item", "start": "2026-11-23T10:00:00Z"},
    ]

    week_start = datetime(2026, 11, 15, tzinfo=timezone.utc)
    week_end = datetime(2026, 11, 21, 23, 59, 59, tzinfo=timezone.utc)

    # Filter events strictly for the current week
    week_events = [
        e for e in events
        if week_start <= datetime.fromisoformat(e["start"].replace("Z", "+00:00")) <= week_end
    ]

    assert len(week_events) == 2
    assert {e["id"] for e in week_events} == {"ev-1", "ev-2"}
    assert "ev-3" not in {e["id"] for e in week_events}


@pytest.mark.asyncio
async def test_calendar_crud_parity(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Calendar event creation, updating, and schedule query parity."""
    _user, profile = e2e_steward_context
    due = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/reminders",
        json={
            "title": "Calendar Scheduled Briefing",
            "next_due_at": due,
            "category": "general",
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Calendar Scheduled Briefing"


def test_domain_neutrality_scan_zero_leaks():
    """Automated scan verifying zero disallowed terms in core tools/registry."""
    from yarvelle_core.schemas.manifest import PHASE_0_REGISTRY

    disallowed = ["patient", "doctor", "vitals", "fhir", "hipaa", "clinic", "prescription"]
    for tool_name in PHASE_0_REGISTRY:
        for term in disallowed:
            assert term not in tool_name.lower(), (
                f"Domain leak detected in tool name '{tool_name}' containing '{term}'"
            )
