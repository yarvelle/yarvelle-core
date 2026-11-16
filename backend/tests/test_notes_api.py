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

"""Comprehensive unit tests for the Notes REST API (Issue #65)."""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from yarvelle_core.api.app import create_app
from yarvelle_core.db.models import Note, Profile, User
from yarvelle_core.testing.fixtures import create_test_session_factory


@pytest.fixture
async def notes_test_env():
    """Sets up an isolated database, test steward user & profiles, and an AsyncClient."""
    async with create_test_session_factory() as (_engine, session_factory):
        async with session_factory() as session:
            user = User(
                id=str(uuid.uuid4()),
                email="notes_steward@test.local",
                username="notes_steward",
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

        from yarvelle_core.api.deps import get_current_user, get_db
        from yarvelle_core.auth.ports import UserProfile

        from datetime import datetime, timezone
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
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield {
                "client": client,
                "user": steward_user,
                "profile_a": profile_a.id,
                "profile_b": profile_b.id,
                "session_factory": session_factory,
            }


@pytest.mark.asyncio
async def test_notes_profile_scoped_full_crud(notes_test_env):
    """Verifies full Create, Read, Update, Delete lifecycle for profile-scoped notes."""
    client: AsyncClient = notes_test_env["client"]
    prof_a: str = notes_test_env["profile_a"]

    # 1. Create Note
    create_payload = {
        "title": "Release Verification Plan",
        "content": "Verify all automated safety tests and performance metrics.",
        "type": "prep",
        "tags": ["release", "verification", "milestone"],
        "pinned": True,
    }
    resp = await client.post(f"/api/v1/profiles/{prof_a}/notes", json=create_payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["title"] == "Release Verification Plan"
    assert created["content"] == create_payload["content"]
    assert created["type"] == "prep"
    assert created["tags"] == ["release", "verification", "milestone"]
    assert created["pinned"] is True
    assert created["profile_id"] == prof_a
    note_id = created["id"]

    # 2. Get Note by ID
    get_resp = await client.get(f"/api/v1/profiles/{prof_a}/notes/{note_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["id"] == note_id
    assert fetched["title"] == "Release Verification Plan"

    # 3. Patch Note
    patch_payload = {
        "title": "Updated Release Verification Plan",
        "pinned": False,
        "tags": ["release", "qa"],
    }
    patch_resp = await client.patch(f"/api/v1/profiles/{prof_a}/notes/{note_id}", json=patch_payload)
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["title"] == "Updated Release Verification Plan"
    assert patched["pinned"] is False
    assert patched["tags"] == ["release", "qa"]
    assert patched["content"] == create_payload["content"]

    # 4. List Notes
    list_resp = await client.get(f"/api/v1/profiles/{prof_a}/notes")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert any(n["id"] == note_id for n in list_data["notes"])

    # 5. Delete Note
    del_resp = await client.delete(f"/api/v1/profiles/{prof_a}/notes/{note_id}")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["success"] is True
    assert del_data["id"] == note_id

    # 6. Verify 404 after deletion
    after_del = await client.get(f"/api/v1/profiles/{prof_a}/notes/{note_id}")
    assert after_del.status_code == 404


@pytest.mark.asyncio
async def test_notes_query_filters(notes_test_env):
    """Verifies filtering by category/type, tag, pinned status, and search string."""
    client: AsyncClient = notes_test_env["client"]
    prof_a: str = notes_test_env["profile_a"]

    # Seed 3 distinct notes
    notes_data = [
        {"title": "Alpha Item", "content": "Deployment checklist", "type": "prep", "tags": ["deploy", "ops"], "pinned": True},
        {"title": "Beta Item", "content": "Weekly summary report", "type": "summary", "tags": ["weekly", "ops"], "pinned": False},
        {"title": "Gamma Item", "content": "Scratchpad ideas", "type": "scratchpad", "tags": ["ideas"], "pinned": False},
    ]
    for n in notes_data:
        resp = await client.post(f"/api/v1/profiles/{prof_a}/notes", json=n)
        assert resp.status_code == 201

    # Filter by type=prep
    resp_prep = await client.get(f"/api/v1/profiles/{prof_a}/notes?type=prep")
    assert resp_prep.status_code == 200
    assert len(resp_prep.json()["notes"]) == 1
    assert resp_prep.json()["notes"][0]["title"] == "Alpha Item"

    # Filter by pinned=true
    resp_pinned = await client.get(f"/api/v1/profiles/{prof_a}/notes?pinned=true")
    assert resp_pinned.status_code == 200
    assert len(resp_pinned.json()["notes"]) == 1
    assert resp_pinned.json()["notes"][0]["title"] == "Alpha Item"

    # Filter by tag=ops (should match Alpha and Beta)
    resp_ops = await client.get(f"/api/v1/profiles/{prof_a}/notes?tag=ops")
    assert resp_ops.status_code == 200
    assert len(resp_ops.json()["notes"]) == 2

    # Filter by search=checklist
    resp_search = await client.get(f"/api/v1/profiles/{prof_a}/notes?search=checklist")
    assert resp_search.status_code == 200
    assert len(resp_search.json()["notes"]) == 1
    assert resp_search.json()["notes"][0]["title"] == "Alpha Item"


@pytest.mark.asyncio
async def test_notes_profile_isolation(notes_test_env):
    """Verifies that note scoped to profile A is inaccessible via profile B."""
    client: AsyncClient = notes_test_env["client"]
    prof_a: str = notes_test_env["profile_a"]
    prof_b: str = notes_test_env["profile_b"]

    resp = await client.post(
        f"/api/v1/profiles/{prof_a}/notes",
        json={"title": "Confidential to A", "content": "Restricted"},
    )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    # Querying note under profile B must return 404
    cross_resp = await client.get(f"/api/v1/profiles/{prof_b}/notes/{note_id}")
    assert cross_resp.status_code == 404

    # Patching note under profile B must return 404
    cross_patch = await client.patch(
        f"/api/v1/profiles/{prof_b}/notes/{note_id}",
        json={"title": "Hacked"},
    )
    assert cross_patch.status_code == 404

    # Deleting note under profile B must return 404
    cross_del = await client.delete(f"/api/v1/profiles/{prof_b}/notes/{note_id}")
    assert cross_del.status_code == 404


@pytest.mark.asyncio
async def test_notes_null_bytes_and_unicode_normalization(notes_test_env):
    """Verifies null byte rejection and Unicode NFC normalization."""
    client: AsyncClient = notes_test_env["client"]
    prof_a: str = notes_test_env["profile_a"]

    # Null byte in title
    resp_null = await client.post(
        f"/api/v1/profiles/{prof_a}/notes",
        json={"title": "Bad\x00Title", "content": "Content"},
    )
    assert resp_null.status_code in (400, 422)

    # Unicode with emoji and accents
    raw_title = "Café \u2615 Overview"
    resp_unicode = await client.post(
        f"/api/v1/profiles/{prof_a}/notes",
        json={"title": raw_title, "content": "Unicode notes"},
    )
    assert resp_unicode.status_code == 201
    data = resp_unicode.json()
    assert data["title"] == unicodedata.normalize("NFC", raw_title)


@pytest.mark.asyncio
async def test_direct_notes_multi_tenant_isolation():
    """Verifies that direct /notes and /notes/{note_id} endpoints enforce multi-tenant profile isolation.

    User 2 cannot list, read, patch, or delete User 1's notes via direct routes.
    """
    from datetime import datetime, timezone
    from yarvelle_core.api.deps import get_current_user, get_db
    from yarvelle_core.auth.ports import UserProfile

    async with create_test_session_factory() as (_engine, session_factory):
        async with session_factory() as session:
            u1 = User(
                id=str(uuid.uuid4()),
                email="user1@test.local",
                username="user1",
                hashed_password="hash",
                status="active",
                role="user",
            )
            u2 = User(
                id=str(uuid.uuid4()),
                email="user2@test.local",
                username="user2",
                hashed_password="hash",
                status="active",
                role="user",
            )
            session.add_all([u1, u2])
            await session.flush()

            p1 = Profile(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                name="User 1 Profile",
            )
            p2 = Profile(
                id=str(uuid.uuid4()),
                user_id=u2.id,
                name="User 2 Profile",
            )
            session.add_all([p1, p2])
            await session.commit()

        app = create_app()

        async def _override_db():
            async with session_factory() as s:
                yield s

        now = datetime.now(timezone.utc)
        u1_prof = UserProfile(
            id=u1.id,
            email=u1.email,
            username=u1.username,
            role="user",
            status="active",
            created_at=now,
            updated_at=now,
        )
        u2_prof = UserProfile(
            id=u2.id,
            email=u2.email,
            username=u2.username,
            role="user",
            status="active",
            created_at=now,
            updated_at=now,
        )

        active_user = {"u": u1_prof}
        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: active_user["u"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. User 1 creates note in Profile 1 via direct POST /notes
            u1_note_resp = await client.post(
                "/api/v1/notes",
                json={
                    "title": "U1 Secret Note",
                    "content": "Confidential content for U1 only.",
                    "profile_id": p1.id,
                    "type": "prep",
                },
            )
            assert u1_note_resp.status_code in (200, 201)
            u1_note_id = u1_note_resp.json()["id"]

            # 2. Switch context to User 2
            active_user["u"] = u2_prof

            # Attack A: User 2 lists direct /notes without profile_id (must NOT include U1's note)
            leak_list = await client.get("/api/v1/notes")
            assert leak_list.status_code == 200
            leaked_ids = [n["id"] for n in leak_list.json().get("notes", [])]
            assert u1_note_id not in leaked_ids, "Critical IDOR: User 2 received User 1's note in /notes listing!"

            # Attack B: User 2 attempts to query /notes?profile_id={p1.id} (must be 403 Forbidden)
            leak_prof_list = await client.get(f"/api/v1/notes?profile_id={p1.id}")
            assert leak_prof_list.status_code == 403, f"Expected 403, got {leak_prof_list.status_code}"

            # Attack C: User 2 attempts to read U1 note via /notes/{note_id} (must be 403 Forbidden)
            leak_get = await client.get(f"/api/v1/notes/{u1_note_id}")
            assert leak_get.status_code == 403, f"Expected 403, got {leak_get.status_code}"

            # Attack D: User 2 attempts to patch U1 note via /notes/{note_id} (must be 403 Forbidden)
            leak_patch = await client.patch(
                f"/api/v1/notes/{u1_note_id}",
                json={"title": "Compromised by U2"},
            )
            assert leak_patch.status_code == 403, f"Expected 403, got {leak_patch.status_code}"

            # Attack E: User 2 attempts to delete U1 note via /notes/{note_id} (must be 403 Forbidden)
            leak_del = await client.delete(f"/api/v1/notes/{u1_note_id}")
            assert leak_del.status_code == 403, f"Expected 403, got {leak_del.status_code}"

            # Attack F: User 2 attempts to create note bound to U1's profile_id (must be 403 Forbidden)
            leak_create = await client.post(
                "/api/v1/notes",
                json={
                    "title": "Illicit U2 Note in P1",
                    "content": "Malicious payload.",
                    "profile_id": p1.id,
                },
            )
            assert leak_create.status_code == 403, f"Expected 403, got {leak_create.status_code}"

            # 3. Switch back to User 1 - operations must succeed
            active_user["u"] = u1_prof

            u1_get = await client.get(f"/api/v1/notes/{u1_note_id}")
            assert u1_get.status_code == 200
            assert u1_get.json()["title"] == "U1 Secret Note"

            u1_patch = await client.patch(
                f"/api/v1/notes/{u1_note_id}",
                json={"title": "Updated Legitimately by U1"},
            )
            assert u1_patch.status_code == 200
            assert u1_patch.json()["title"] == "Updated Legitimately by U1"

            u1_del = await client.delete(f"/api/v1/notes/{u1_note_id}")
            assert u1_del.status_code == 200

            u1_after_del = await client.get(f"/api/v1/notes/{u1_note_id}")
            assert u1_after_del.status_code == 404
