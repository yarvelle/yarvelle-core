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

"""Comprehensive unit tests for Core Entities Parity and Domain Leak Purge (Issue #67)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from yarvelle_core.api.app import create_app
from yarvelle_core.api.deps import get_current_user, get_db
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Profile, User
from yarvelle_core.platform.email_drafts import (
    VALID_DRAFT_CATEGORIES,
    create_email_draft,
    execute_delete_email_draft,
    execute_list_email_drafts,
)
from yarvelle_core.scope.context import (
    DEFAULT_GRANTED_SCOPES,
    DEFAULT_HEALTH_GRANTED_SCOPES,
)
from yarvelle_core.testing.fixtures import create_test_session_factory
from yarvelle_core.tools.reminders import (
    VALID_REMINDER_CATEGORIES,
    execute_create_reminder,
    execute_delete_reminder,
    execute_update_reminder,
    register_reminder_category,
)


@pytest.fixture
async def parity_test_env():
    """Sets up an isolated database, test steward user & profiles, and an AsyncClient."""
    async with create_test_session_factory() as (_engine, session_factory):
        async with session_factory() as session:
            user = User(
                id=str(uuid.uuid4()),
                email="parity_steward@test.local",
                username="parity_steward",
                hashed_password="hash",
                status="active",
                role="admin",
            )
            session.add(user)
            await session.flush()

            profile_a = Profile(
                id=str(uuid.uuid4()),
                user_id=user.id,
                name="Primary Profile",
            )
            profile_b = Profile(
                id=str(uuid.uuid4()),
                user_id=user.id,
                name="Secondary Profile",
            )
            session.add_all([profile_a, profile_b])
            await session.commit()

        app = create_app()

        async def _override_db():
            async with session_factory() as session:
                yield session

        now = datetime.now(timezone.utc)
        steward_user = UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            role="admin",
            status="active",
            created_at=now,
            updated_at=now,
        )

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: steward_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield {
                "client": client,
                "profile_a": profile_a,
                "profile_b": profile_b,
                "user": user,
                "session_factory": session_factory,
            }


@pytest.mark.asyncio
async def test_email_draft_patch_api(parity_test_env):
    """PATCH /profiles/{profile_id}/email-drafts/{draft_id} updates subject, body, category, and recipient."""
    client: AsyncClient = parity_test_env["client"]
    profile_a: Profile = parity_test_env["profile_a"]
    profile_b: Profile = parity_test_env["profile_b"]

    # 1. Create a draft
    create_resp = await client.post(
        f"/api/v1/profiles/{profile_a.id}/email-drafts",
        json={
            "recipient": "info@example.com",
            "subject": "Initial Inquiry",
            "body": "Initial message body.",
            "category": "inquiry",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    draft_id = created["id"]
    assert created["subject"] == "Initial Inquiry"
    assert created["category"] == "inquiry"

    # 2. Patch draft
    patch_resp = await client.patch(
        f"/api/v1/profiles/{profile_a.id}/email-drafts/{draft_id}",
        json={
            "recipient": "updated@example.com",
            "subject": "Updated Subject Line",
            "body": "Revised message body content.",
            "category": "administrative",
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    updated = patch_resp.json()
    assert updated["id"] == draft_id
    assert updated["recipient"] == "updated@example.com"
    assert updated["subject"] == "Updated Subject Line"
    assert updated["body"] == "Revised message body content."
    assert updated["category"] == "administrative"

    # 3. Non-existent draft 404
    missing_resp = await client.patch(
        f"/api/v1/profiles/{profile_a.id}/email-drafts/non-existent-draft-id",
        json={"subject": "Doesn't Matter"},
    )
    assert missing_resp.status_code == 404

    # 4. Cross-profile isolation: profile_b cannot patch profile_a's draft
    cross_resp = await client.patch(
        f"/api/v1/profiles/{profile_b.id}/email-drafts/{draft_id}",
        json={"subject": "Illegal Modification"},
    )
    assert cross_resp.status_code == 404


@pytest.mark.asyncio
async def test_email_draft_patch_invalid_category_rejected(parity_test_env):
    """PATCH /profiles/{profile_id}/email-drafts/{draft_id} with invalid category returns HTTP 400 with YRV-100-003."""
    client: AsyncClient = parity_test_env["client"]
    profile_a: Profile = parity_test_env["profile_a"]

    # Create a draft
    create_resp = await client.post(
        f"/api/v1/profiles/{profile_a.id}/email-drafts",
        json={
            "recipient": "info@example.com",
            "subject": "Category Validation Test",
            "body": "Test message body.",
            "category": "inquiry",
        },
    )
    assert create_resp.status_code == 201
    draft_id = create_resp.json()["id"]

    # Patch with invalid category
    bad_patch = await client.patch(
        f"/api/v1/profiles/{profile_a.id}/email-drafts/{draft_id}",
        json={"category": "unsupported_invalid_category"},
    )
    assert bad_patch.status_code == 400
    problem = bad_patch.json()
    assert "YRV-100-003" in str(problem)


@pytest.mark.asyncio
async def test_routines_get_and_delete_api(parity_test_env):
    """GET and DELETE /profiles/{profile_id}/routines/{routine_id} provide full routine lifecycle parity."""
    client: AsyncClient = parity_test_env["client"]
    profile_a: Profile = parity_test_env["profile_a"]
    profile_b: Profile = parity_test_env["profile_b"]
    user: User = parity_test_env["user"]
    session_factory = parity_test_env["session_factory"]

    # Seed 2 active connections for profile_a to meet A2 autonomy prerequisites
    from yarvelle_core.db.models import Connection
    async with session_factory() as session:
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=user.id,
                profile_id=profile_a.id,
                connector_id="mock_conn_alpha",
                status="active",
            )
        )
        session.add(
            Connection(
                id=str(uuid.uuid4()),
                user_id=user.id,
                profile_id=profile_a.id,
                connector_id="mock_conn_beta",
                status="active",
            )
        )
        await session.commit()

    # 1. Create routine
    create_resp = await client.post(
        f"/api/v1/profiles/{profile_a.id}/routines",
        json={
            "name": "Evening Workspace Review",
            "description": "Daily wrap-up routine",
            "tool_name": "workspace-note",
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "timezone": "UTC",
            "args": {"review": "daily"},
        },
    )
    assert create_resp.status_code in (200, 201), create_resp.text
    routine = create_resp.json()
    routine_id = routine["id"]
    assert routine["name"] == "Evening Workspace Review"

    # 2. GET routine by ID
    get_resp = await client.get(f"/api/v1/profiles/{profile_a.id}/routines/{routine_id}")
    assert get_resp.status_code == 200, get_resp.text
    fetched = get_resp.json()
    assert fetched["id"] == routine_id
    assert fetched["name"] == "Evening Workspace Review"
    assert fetched["profile_id"] == profile_a.id

    # 3. GET non-existent routine -> 404
    get_missing = await client.get(f"/api/v1/profiles/{profile_a.id}/routines/missing-routine-id")
    assert get_missing.status_code == 404

    # 4. Cross-profile GET isolation
    cross_get = await client.get(f"/api/v1/profiles/{profile_b.id}/routines/{routine_id}")
    assert cross_get.status_code == 404

    # 5. Cross-profile DELETE isolation
    cross_del = await client.delete(f"/api/v1/profiles/{profile_b.id}/routines/{routine_id}")
    assert cross_del.status_code == 404

    # 6. DELETE routine
    del_resp = await client.delete(f"/api/v1/profiles/{profile_a.id}/routines/{routine_id}")
    assert del_resp.status_code in (200, 204), del_resp.text
    assert del_resp.json()["deleted"] is True

    # 7. Subsequent GET returns 404
    post_del_get = await client.get(f"/api/v1/profiles/{profile_a.id}/routines/{routine_id}")
    assert post_del_get.status_code == 404


def test_domain_leak_purge_and_categories():
    """Verify purge of domain-specific leaks in reminder categories, email draft categories, and default scopes."""
    # 1. Reminder categories
    assert "medication" not in VALID_REMINDER_CATEGORIES
    expected_categories = {"task", "event", "prep", "general", "appointment"}
    assert expected_categories.issubset(VALID_REMINDER_CATEGORIES)

    # Dynamic registration
    custom_category = "ops_logistics"
    register_reminder_category(custom_category)
    assert custom_category in VALID_REMINDER_CATEGORIES

    # 2. Email draft categories
    assert "insurance" not in VALID_DRAFT_CATEGORIES
    assert "inquiry" in VALID_DRAFT_CATEGORIES
    assert "administrative" in VALID_DRAFT_CATEGORIES

    # 3. Scopes domain neutrality
    assert DEFAULT_GRANTED_SCOPES == frozenset({"core", "core.*", "*"})
    assert DEFAULT_HEALTH_GRANTED_SCOPES == DEFAULT_GRANTED_SCOPES


class DummyContext:
    """Mock ToolContext for testing tool handlers."""

    def __init__(self, profile_id: str, session_factory: Any = None):
        self.profile_id = profile_id
        self.user_id = "test_user"
        self.session_factory = session_factory


@pytest.mark.asyncio
async def test_email_draft_tools_parity(parity_test_env):
    """Verify tool executors execute_list_email_drafts and execute_delete_email_draft."""
    profile_a: Profile = parity_test_env["profile_a"]
    session_factory = parity_test_env["session_factory"]
    ctx = DummyContext(profile_id=profile_a.id, session_factory=session_factory)

    # Create a draft via helper
    async with session_factory() as session:
        draft = await create_email_draft(
            session=session,
            profile_id=profile_a.id,
            recipient="test@example.com",
            subject="Tool Draft Test",
            body="Content for tool execution.",
            category="inquiry",
        )
        draft_id = draft.id

    # List drafts tool
    list_result = await execute_list_email_drafts({}, ctx=ctx)
    assert list_result["total"] >= 1
    draft_ids = [d["id"] for d in list_result["drafts"]]
    assert draft_id in draft_ids

    # Delete draft tool
    del_result = await execute_delete_email_draft({"draft_id": draft_id}, ctx=ctx)
    assert del_result["deleted"] is True
    assert del_result["id"] == draft_id

    # Verify no longer listed
    list_after = await execute_list_email_drafts({}, ctx=ctx)
    draft_ids_after = [d["id"] for d in list_after["drafts"]]
    assert draft_id not in draft_ids_after


@pytest.mark.asyncio
async def test_reminder_tools_parity(parity_test_env, monkeypatch):
    """Verify tool executors execute_update_reminder and execute_delete_reminder."""
    profile_a: Profile = parity_test_env["profile_a"]
    session_factory = parity_test_env["session_factory"]
    ctx = DummyContext(profile_id=profile_a.id)

    # Monkeypatch get_session_factory to use our test session factory
    from yarvelle_core.db import session as db_session_module
    from yarvelle_core.tools import reminders as reminders_tool_module

    monkeypatch.setattr(reminders_tool_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(db_session_module, "get_session_factory", lambda: session_factory)

    due_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    create_res = await execute_create_reminder(
        {"title": "Initial Reminder", "next_due_at": due_time, "category": "general"},
        ctx=ctx,
    )
    assert create_res.success is True, create_res.error
    rem_id = create_res.output["id"]

    # Update reminder
    update_res = await execute_update_reminder(
        {"id": rem_id, "title": "Updated Reminder Title", "category": "task"},
        ctx=ctx,
    )
    assert update_res.success is True, update_res.error
    assert update_res.output["title"] == "Updated Reminder Title"
    assert update_res.output["category"] == "task"

    # Delete reminder
    del_res = await execute_delete_reminder({"id": rem_id}, ctx=ctx)
    assert del_res.success is True, del_res.error
    assert del_res.output["deleted"] is True

    # Deleting again returns error
    del_again = await execute_delete_reminder({"id": rem_id}, ctx=ctx)
    assert del_again.success is False
