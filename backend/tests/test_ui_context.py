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

"""Tests for UI context and UI preferences endpoints (/api/v1/me/ui-context and /api/v1/me/profiles/{id}/ui-prefs)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yarvelle_core.api.deps import get_current_user
from yarvelle_core.api.router import api_router
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Base, Profile, ProfileAccess, ProfileUiPreference, ScopeGrant, User
from yarvelle_core.db.scoped_session import ScopedAsyncSession
from yarvelle_core.db.session import get_db


@pytest.fixture
async def test_app_and_client():
    """Sets up an in-memory SQLite DB, FastAPI application with api_router, and httpx client."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=ScopedAsyncSession)

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_user():
        return DEFAULT_STEWARD_USER

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_ui_context_lifecycle(test_app_and_client):
    client, session_factory = test_app_and_client

    # 1. Create adult, teen, and child profiles
    today = date.today()
    adult_dob = (today - timedelta(days=30 * 365)).isoformat()
    teen_dob = (today - timedelta(days=15 * 365)).isoformat()
    child_dob = (today - timedelta(days=8 * 365)).isoformat()

    async with session_factory() as session:
        adult_p = Profile(
            id="p-adult-01",
            name="Adult Profile",
            role="self",
            date_of_birth=adult_dob,
        )
        teen_p = Profile(
            id="p-teen-01",
            name="Teen Profile",
            role="self",
            date_of_birth=teen_dob,
        )
        child_p = Profile(
            id="p-child-01",
            name="Child Profile",
            role="self",
            date_of_birth=child_dob,
        )
        viewer_p = Profile(
            id="p-viewer-01",
            name="Viewer Profile",
            role="viewer",
            date_of_birth=adult_dob,
        )
        session.add_all([adult_p, teen_p, child_p, viewer_p])

        # Add scope grants for adult
        grant1 = ScopeGrant(
            profile_id="p-adult-01",
            scope="health.clinical",
            access_level="read",
        )
        grant2 = ScopeGrant(
            profile_id="p-adult-01",
            scope="finance.accounts",
            access_level="read",
        )
        session.add_all([grant1, grant2])
        await session.commit()

    # 2. Test GET /api/v1/me/ui-context for adult profile
    res = await client.get("/api/v1/me/ui-context?profile_id=p-adult-01")
    assert res.status_code == 200
    data = res.json()
    assert data["profile_id"] == "p-adult-01"
    assert data["audience"] == "adult"
    assert "health.clinical" in data["scopes"]
    assert "finance.accounts" in data["scopes"]
    assert data["hidden_panels"] == []

    # 3. Test GET /api/v1/me/ui-context for teen profile
    res = await client.get("/api/v1/me/ui-context?profile_id=p-teen-01")
    assert res.status_code == 200
    assert res.json()["audience"] == "teen"

    # 4. Test GET /api/v1/me/ui-context for child profile
    res = await client.get("/api/v1/me/ui-context?profile_id=p-child-01")
    assert res.status_code == 200
    assert res.json()["audience"] == "child"

    # 5. Test GET /api/v1/me/ui-context for viewer profile
    res = await client.get("/api/v1/me/ui-context?profile_id=p-viewer-01")
    assert res.status_code == 200
    assert res.json()["audience"] == "viewer"

    # 6. Test GET /api/v1/me/profiles/{profile_id}/ui-prefs (initially empty)
    res = await client.get("/api/v1/me/profiles/p-adult-01/ui-prefs")
    assert res.status_code == 200
    assert res.json()["hidden_panels"] == []
    assert res.json()["theme_preference"] is None

    # 7. Test PUT /api/v1/me/profiles/{profile_id}/ui-prefs
    put_res = await client.put(
        "/api/v1/me/profiles/p-adult-01/ui-prefs",
        json={
            "hidden_panels": ["finance.budget", "health.vitals"],
            "theme_preference": "dark",
        },
    )
    assert put_res.status_code == 200
    put_data = put_res.json()
    assert put_data["hidden_panels"] == ["finance.budget", "health.vitals"]
    assert put_data["theme_preference"] == "dark"

    # 8. Verify GET /api/v1/me/ui-context reflects the updated hidden_panels
    res_updated = await client.get("/api/v1/me/ui-context?profile_id=p-adult-01")
    assert res_updated.status_code == 200
    assert res_updated.json()["hidden_panels"] == ["finance.budget", "health.vitals"]

    # 9. Test unknown profile returns 404
    res_404 = await client.get("/api/v1/me/profiles/p-unknown/ui-prefs")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_ui_context_regular_member_user_and_headers(test_app_and_client):
    """Verifies that non-admin/regular members do NOT hit NameError (HTTP 500) and headers resolve correctly."""
    client, session_factory = test_app_and_client
    app = client._transport.app

    now = datetime.now(timezone.utc)
    alice_user = UserProfile(
        id="user_alice",
        username="alice",
        email="alice@example.com",
        role="member",
        created_at=now,
        updated_at=now,
    )
    bob_user = UserProfile(
        id="user_bob",
        username="bob",
        email="bob@example.com",
        role="member",
        created_at=now,
        updated_at=now,
    )

    async with session_factory() as session:
        p_alice_1 = Profile(
            id="p-alice-primary",
            user_id="user_alice",
            name="Alice Self",
            role="self",
            is_primary=True,
            date_of_birth="1992-04-12",
        )
        p_alice_2 = Profile(
            id="p-alice-secondary",
            user_id="user_alice",
            name="Alice Child",
            role="guardian",
            is_primary=False,
            date_of_birth="2018-09-01",
        )
        p_bob_1 = Profile(
            id="p-bob-primary",
            user_id="user_bob",
            name="Bob Self",
            role="self",
            is_primary=True,
            date_of_birth="1988-11-20",
        )
        session.add_all([p_alice_1, p_alice_2, p_bob_1])

        # Scope grants for Alice's primary profile
        session.add(
            ScopeGrant(
                profile_id="p-alice-primary",
                user_id="user_alice",
                scope="health.records",
                access_level="read",
            )
        )
        await session.commit()

    # Authenticate as regular member Alice
    app.dependency_overrides[get_current_user] = lambda: alice_user

    # 1. Accessing own profile with query param succeeds without NameError
    res_param = await client.get("/api/v1/me/ui-context?profile_id=p-alice-primary")
    assert res_param.status_code == 200, f"Expected 200 but got {res_param.status_code}: {res_param.text}"
    data = res_param.json()
    assert data["profile_id"] == "p-alice-primary"
    assert "health.records" in data["scopes"]

    # 2. Accessing without profile_id resolves Alice's primary profile
    res_default = await client.get("/api/v1/me/ui-context")
    assert res_default.status_code == 200
    assert res_default.json()["profile_id"] == "p-alice-primary"

    # 3. Resolving via X-Profile-ID header (uppercase)
    res_header_upper = await client.get(
        "/api/v1/me/ui-context",
        headers={"X-Profile-ID": "p-alice-secondary"},
    )
    assert res_header_upper.status_code == 200
    assert res_header_upper.json()["profile_id"] == "p-alice-secondary"

    # 4. Resolving via x-profile-id header (lowercase)
    res_header_lower = await client.get(
        "/api/v1/me/ui-context",
        headers={"x-profile-id": "p-alice-secondary"},
    )
    assert res_header_lower.status_code == 200
    assert res_header_lower.json()["profile_id"] == "p-alice-secondary"

    # 5. Query param takes precedence over header if both are supplied
    res_both = await client.get(
        "/api/v1/me/ui-context?profile_id=p-alice-primary",
        headers={"X-Profile-ID": "p-alice-secondary"},
    )
    assert res_both.status_code == 200
    assert res_both.json()["profile_id"] == "p-alice-primary"

    # 6. Accessing Bob's profile returns 403 Forbidden
    res_forbidden = await client.get("/api/v1/me/ui-context?profile_id=p-bob-primary")
    assert res_forbidden.status_code == 403
    assert "Access to profile denied" in res_forbidden.json()["detail"]

    # 7. Updating prefs for Bob's profile returns 403 Forbidden
    put_forbidden = await client.put(
        "/api/v1/me/profiles/p-bob-primary/ui-prefs",
        json={"hidden_panels": ["health.vitals"]},
    )
    assert put_forbidden.status_code == 403

    # 8. Updating prefs for own profile succeeds
    put_own = await client.put(
        "/api/v1/me/profiles/p-alice-primary/ui-prefs",
        json={"hidden_panels": ["finance.budget"], "theme_preference": "dark"},
    )
    assert put_own.status_code == 200
    assert put_own.json()["hidden_panels"] == ["finance.budget"]


@pytest.mark.asyncio
async def test_ui_context_multiuser_isolation_empty_profiles(test_app_and_client):
    """Verifies that a member user with no profiles does NOT inadvertently see other users' profiles."""
    client, session_factory = test_app_and_client
    app = client._transport.app

    now = datetime.now(timezone.utc)
    charlie_user = UserProfile(
        id="user_charlie_isolated",
        username="charlie",
        email="charlie@example.com",
        role="member",
        created_at=now,
        updated_at=now,
    )

    # Charlie has no profiles
    app.dependency_overrides[get_current_user] = lambda: charlie_user

    res = await client.get("/api/v1/me/ui-context")
    assert res.status_code == 404
    assert "No profile found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_ui_context_shared_profile_access(test_app_and_client):
    """Verifies that a user granted access via ProfileAccess can retrieve UI context."""
    client, session_factory = test_app_and_client
    app = client._transport.app

    now = datetime.now(timezone.utc)
    dan_user = UserProfile(
        id="user_dan",
        username="dan",
        email="dan@example.com",
        role="member",
        created_at=now,
        updated_at=now,
    )

    async with session_factory() as session:
        p_shared = Profile(
            id="p-shared-target",
            user_id="user_owner_other",
            name="Shared Profile",
            role="self",
        )
        access = ProfileAccess(
            profile_id="p-shared-target",
            user_id="user_dan",
            access_level="view",
        )
        session.add_all([p_shared, access])
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: dan_user

    res = await client.get("/api/v1/me/ui-context?profile_id=p-shared-target")
    assert res.status_code == 200
    assert res.json()["profile_id"] == "p-shared-target"

