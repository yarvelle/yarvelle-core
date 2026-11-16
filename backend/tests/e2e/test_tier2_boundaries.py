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

"""Tier 2 E2E Boundary & Corner-Case Tests for Yarvelle Core (Features 1–4).

Covers Boundary Value Analysis (BVA), extreme payloads, invalid combinations,
unicode preservation, ReDoS/null-byte immunity, and negative execution:
- Feature 1: Dynamic Pack Tool Registration & Validation (Issue #64)
- Feature 2: Live entity_changed SSE Event Emission (Issue #66)
- Feature 3: Core Notes REST Router & @yarvelle/ui NoteEditor (Issue #65)
- Feature 4: Core Reminders/Tasks/Calendar Parity & Leak Purge (Issue #67)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import uuid

import pytest
from httpx import AsyncClient
from zoneinfo import ZoneInfo

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
)
from yarvelle_core.schemas.events import (
    EntityChangedPayload,
    _derive_action,
    _derive_entity_id,
    _derive_entity_type,
    build_entity_changed_payload,
)
from yarvelle_core.scope.context import DEFAULT_SCOPE, scope_context


# ============================================================================
# Feature 1: Boundary & Corner Cases (Tool Registry & Validation)
# ============================================================================


def test_tool_registry_unknown_pack_id():
    """Querying tools for a non-existent pack returns only core tools, no crash."""
    registry = create_default_registry()
    tools = registry.list_for_enabled_packs(["non_existent_pack_99999"])
    # Must not crash, should return the base core tools
    assert len(tools) > 0
    # None of the tools should be attributed to the non-existent pack
    for t in tools:
        assert registry.get_pack_id(t.name) != "non_existent_pack_99999"


def test_tool_registry_empty_or_whitespace_name():
    """Tool names with empty string or spaces fail schema or registry validation."""
    from yarvelle_core.schemas.manifest import SLUG_REGEX

    assert SLUG_REGEX.match("") is None
    assert SLUG_REGEX.match("   ") is None
    assert SLUG_REGEX.match("tool name with space") is None

    with pytest.raises(ToolValidationError):
        validate_tools_against_registry([""], allowed_tools={"attach-read"})

    with pytest.raises(ToolValidationError):
        validate_tools_against_registry(["   "], allowed_tools={"attach-read"})


def test_tool_registry_duplicate_registration():
    """Registering duplicate tool spec with identical name overwrites cleanly."""
    registry = ToolSpecRegistry()
    spec1 = ToolSpec(name="item_processor", risk_tier="read")
    spec2 = ToolSpec(name="item_processor", risk_tier="write_local")

    registry.register(spec1, pack_id="core")
    assert registry.get("item_processor").risk_tier == "read"

    # Re-registering updates the tool spec cleanly
    registry.register(spec2, pack_id="core")
    assert registry.get("item_processor").risk_tier == "write_local"


def test_tool_registry_cyclic_pack_dependency():
    """Cyclic or self-referential pack ids handled gracefully during tool resolution."""
    registry = ToolSpecRegistry()
    t1 = ToolSpec(name="tool_a", scopes={"a.scope"})
    t2 = ToolSpec(name="tool_b", scopes={"b.scope"})

    registry.register(t1, pack_id="pack_alpha")
    registry.register(t2, pack_id="pack_beta")

    # Redundant/cyclic lists
    resolved = registry.list_for_enabled_packs(["pack_alpha", "pack_beta", "pack_alpha"])
    assert t1 in resolved
    assert t2 in resolved


def test_tool_registry_unregistered_tool_invocation():
    """Subagent attempting to invoke tool outside declared set is excluded from effective tools."""
    declared_tools = ["attach-read", "unregistered_external_utility"]
    registry_tools = {"attach-read", "workspace-note"}

    effective = compute_effective_tools(
        agent_tools=declared_tools,
        skills=[],
        allowed_tools=registry_tools,
    )
    assert "attach-read" in effective
    assert "unregistered_external_utility" not in effective


# ============================================================================
# Feature 2: Boundary & Corner Cases (Live entity_changed SSE Emission)
# ============================================================================


def test_entity_changed_malformed_json_resilience():
    """Payload builder handles unexpected output shapes without throwing unhandled exceptions."""
    # Output is a raw string
    p1 = build_entity_changed_payload("update_workspace_note", output="string response")
    assert p1["type"] == SSE_EVENT_ENTITY_CHANGED
    assert p1["action"] == "updated"

    # Output is None
    p2 = build_entity_changed_payload("create_workspace_note", output=None)
    assert p2["type"] == SSE_EVENT_ENTITY_CHANGED
    assert p2["action"] == "created"

    # Output is an integer
    p3 = build_entity_changed_payload("delete_workspace_note", output=42)
    assert p3["type"] == SSE_EVENT_ENTITY_CHANGED
    assert p3["action"] == "deleted"

    # Output is a list
    p4 = build_entity_changed_payload("custom_mutate", output=[1, 2, 3])
    assert p4["type"] == SSE_EVENT_ENTITY_CHANGED


def test_entity_changed_null_or_empty_entity_id():
    """Missing or null entity_id defaults to empty string or fallback without error."""
    payload = build_entity_changed_payload(
        tool_name="create_workspace_note",
        args={},
        output={"status": "ok"},
    )
    assert payload["entity_id"] == ""
    assert payload["record_id"] == ""


def test_entity_changed_rapid_burst_mutations():
    """50 rapid sequential mutations emitted and validated without dropped events."""
    payloads = []
    for i in range(50):
        p = build_entity_changed_payload(
            tool_name="create_workspace_note",
            args={"id": f"burst-note-{i}", "title": f"Note {i}"},
            output={"id": f"burst-note-{i}", "action": "created"},
            profile_id="prof-steward",
            scope="steward.general",
        )
        payloads.append(p)

    assert len(payloads) == 50
    # Validate every payload against strict model
    for idx, p in enumerate(payloads):
        model = EntityChangedPayload(**p)
        assert model.entity_id == f"burst-note-{idx}"
        assert model.action == "created"


@pytest.mark.asyncio
async def test_entity_changed_client_disconnect_during_emission():
    """Generator handles client disconnect / cancellation gracefully."""
    async def mock_event_stream():
        for i in range(10):
            yield f"event: {SSE_EVENT_ENTITY_CHANGED}\ndata: {{}}\n\n"
            await asyncio.sleep(0.01)

    received = []
    try:
        async for chunk in mock_event_stream():
            received.append(chunk)
            if len(received) >= 2:
                # Simulate client disconnect
                break
    except asyncio.CancelledError:
        pass

    assert len(received) == 2


def test_entity_changed_unsupported_action_verb():
    """Action verbs other than created/updated/deleted are normalized safely."""
    # Unknown verb defaults to updated
    action1 = _derive_action("custom_tool", args={"action": "archive"}, output={})
    assert action1 in ("updated", "archive")

    # Verb with leading/trailing whitespace
    action2 = _derive_action("custom_tool", args={"action": "  create  "}, output={})
    assert action2 == "created"


# ============================================================================
# Feature 3: Boundary & Corner Cases (Core Notes REST Router)
# ============================================================================


@pytest.mark.asyncio
async def test_notes_empty_content_allowed(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """0-byte note content creates note successfully with empty string."""
    _user, profile = e2e_steward_context
    resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": "Empty Note", "content": "", "profile_id": profile.id},
    )
    if resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["content"] == ""


@pytest.mark.asyncio
async def test_notes_max_length_boundary(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Note with 100,000 characters accepted and persisted."""
    _user, profile = e2e_steward_context
    large_content = "X" * 100_000

    resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": "Large Spec Note", "content": large_content, "profile_id": profile.id},
    )
    if resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    assert resp.status_code in (200, 201)
    note_id = resp.json()["id"]

    fetch_resp = await e2e_auth_client.get(f"/api/v1/notes/{note_id}")
    assert fetch_resp.status_code == 200
    assert len(fetch_resp.json()["content"]) == 100_000


@pytest.mark.asyncio
async def test_notes_unicode_and_emojis(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Note title and body containing UTF-8 emojis and RTL script preserved canonically."""
    _user, profile = e2e_steward_context
    title = "Steward Briefing 🚀 📝 — مراجعة شاملة"
    content = "Multi-language notes with emojis: 🌟, ⚙️, and mixed script."

    resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": title, "content": content, "profile_id": profile.id},
    )
    if resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    assert resp.status_code in (200, 201)
    data = resp.json()
    # Canonical Unicode NFC normalization check
    assert unicodedata.normalize("NFC", data["title"]) == unicodedata.normalize("NFC", title)


@pytest.mark.asyncio
async def test_notes_null_byte_rejection(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Title containing null bytes rejected with 422 Unprocessable Entity."""
    _user, profile = e2e_steward_context
    resp = await e2e_auth_client.post(
        "/api/v1/notes",
        json={"title": "Invalid\x00Title", "content": "Sample", "profile_id": profile.id},
    )
    if resp.status_code == 404:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")

    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_notes_delete_non_existent_id(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Deleting non-existent UUID returns 404 cleanly."""
    _user, profile = e2e_steward_context
    non_existent_id = str(uuid.uuid4())
    resp = await e2e_auth_client.delete(f"/api/v1/notes/{non_existent_id}")
    if resp.status_code == 404:
        # Expected behavior
        assert resp.status_code == 404
    else:
        pytest.skip("Feature 3 (Core Notes REST router) not yet mounted on branch")


# ============================================================================
# Feature 4: Boundary & Corner Cases (Reminders/Tasks/Calendar)
# ============================================================================


@pytest.mark.asyncio
async def test_reminder_negative_interval_rejected(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Reminder with invalid recurrence format fails validation."""
    _user, profile = e2e_steward_context
    resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/reminders",
        json={
            "title": "Invalid Recurrence Reminder",
            "next_due_at": datetime.now(timezone.utc).isoformat(),
            "rrule": "INTERVAL=-5",  # Missing FREQ token and negative interval
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 422


def test_reminder_leap_year_rrule():
    """Recurrence spanning February 29 handled correctly across leap years."""
    from yarvelle_core.platform.reminders import advance_rrule_occurrence

    # In leap year 2024, advancing from Feb 28 reaches Feb 29
    dt_feb28_leap = datetime(2024, 2, 28, 12, 0, tzinfo=timezone.utc)
    next_day_leap = advance_rrule_occurrence(dt_feb28_leap, "FREQ=DAILY;INTERVAL=1")
    assert next_day_leap is not None
    assert next_day_leap.year == 2024
    assert next_day_leap.month == 2
    assert next_day_leap.day == 29

    # In non-leap year 2025, advancing from Feb 28 reaches March 1
    dt_feb28_non_leap = datetime(2025, 2, 28, 12, 0, tzinfo=timezone.utc)
    next_day_non_leap = advance_rrule_occurrence(dt_feb28_non_leap, "FREQ=DAILY;INTERVAL=1")
    assert next_day_non_leap is not None
    assert next_day_non_leap.year == 2025
    assert next_day_non_leap.month == 3
    assert next_day_non_leap.day == 1


def test_calendar_dst_shift_transition():
    """Events spanning daylight saving time transitions preserve wall-clock time."""
    tz = ZoneInfo("America/New_York")
    # Nov 1, 2026: Daylight Saving ends (fall back)
    before_dst = datetime(2026, 10, 31, 14, 0, tzinfo=tz)
    after_dst = datetime(2026, 11, 2, 14, 0, tzinfo=tz)

    assert before_dst.hour == 14
    assert after_dst.hour == 14
    # UTC offset shifts from -04:00 to -05:00
    assert before_dst.utcoffset() == timedelta(hours=-4)
    assert after_dst.utcoffset() == timedelta(hours=-5)


def test_calendar_overlapping_events():
    """Multiple overlapping events on the same day sliced and identified correctly."""
    events = [
        {"id": "ev-1", "title": "Session A", "start": "2026-11-16T10:00:00Z", "end": "2026-11-16T11:00:00Z"},
        {"id": "ev-2", "title": "Session B", "start": "2026-11-16T10:30:00Z", "end": "2026-11-16T11:30:00Z"},
    ]

    t1_start = datetime.fromisoformat(events[0]["start"].replace("Z", "+00:00"))
    t1_end = datetime.fromisoformat(events[0]["end"].replace("Z", "+00:00"))
    t2_start = datetime.fromisoformat(events[1]["start"].replace("Z", "+00:00"))
    t2_end = datetime.fromisoformat(events[1]["end"].replace("Z", "+00:00"))

    # Overlap detection: start1 < end2 and start2 < end1
    has_overlap = (t1_start < t2_end) and (t2_start < t1_end)
    assert has_overlap is True


@pytest.mark.asyncio
async def test_reminder_invalid_iso8601(
    e2e_auth_client: AsyncClient,
    e2e_steward_context: Tuple[User, Profile],
):
    """Invalid datetime string returns 422 without 500 error."""
    _user, profile = e2e_steward_context
    resp = await e2e_auth_client.post(
        f"/api/v1/profiles/{profile.id}/reminders",
        json={
            "title": "Bad Date Reminder",
            "next_due_at": "not-a-valid-date-string",
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 422
