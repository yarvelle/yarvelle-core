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

"""Pack routers are mounted behind auth + scope enforcement (02 §3, §4.2, YV-NFR-7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from yarvelle_core.api.deps import get_current_user
from yarvelle_core.api.router import PackRouterContractError, build_contribution_dependencies, mount_router_contributions
from yarvelle_core.api.scope_guard import iter_api_routes, route_scope_guards
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.config import settings
from yarvelle_core.db.models import Base, Profile, ProfileAccess, ScopeGrant, User
from yarvelle_core.db.session import get_db
from yarvelle_core.pack.spec import RouterContribution

USERS = ("owner", "reader", "writer", "expired", "stranger")


def _pack_router() -> APIRouter:
    router = APIRouter()

    @router.get("")
    async def list_accounts(profile_id: str = Query(...)) -> dict:
        return {"profile_id": profile_id, "accounts": ["acct-1"]}

    @router.post("")
    async def create_account(request: Request, profile_id: str = Query(...)) -> dict:
        return {"created": True, "level": request.state.pack_scope.level}

    return router


def _profile_user(user_id: str) -> UserProfile:
    now = datetime.now(timezone.utc)
    return UserProfile(id=user_id, email=f"{user_id}@example.test", username=user_id, created_at=now, updated_at=now)


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    path = tmp_path / "guard.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add_all([User(id=u, email=f"{u}@example.test", username=u, hashed_password="x") for u in USERS])
        session.flush()
        session.add(Profile(id="prof-1", name="Household", user_id="owner"))
        session.flush()
        session.add_all(
            [
                ProfileAccess(profile_id="prof-1", user_id="reader", access_level="view_paperwork"),
                ProfileAccess(profile_id="prof-1", user_id="writer", access_level="view_paperwork"),
                ProfileAccess(profile_id="prof-1", user_id="expired", access_level="view_paperwork"),
                ScopeGrant(profile_id="prof-1", user_id="reader", scope="finance.accounts", access_level="read"),
                ScopeGrant(profile_id="prof-1", user_id="writer", scope="finance.*", access_level="write"),
                ScopeGrant(
                    profile_id="prof-1",
                    user_id="expired",
                    scope="finance.*",
                    access_level="write",
                    expires_at=now - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()
    engine.dispose()
    return path


def _app(db_file: Path, *, fake_auth: bool = True) -> FastAPI:
    app = FastAPI()
    api = APIRouter()
    mount_router_contributions(
        api,
        [RouterContribution(_pack_router(), prefix="/finance/accounts", pack_id="finance", scope="finance.accounts", level="read")],
    )
    app.include_router(api, prefix="/api/v1")

    async def _db() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
        await engine.dispose()

    app.dependency_overrides[get_db] = _db
    if fake_auth:
        async def _user(request: Request) -> UserProfile:
            uid = request.headers.get("X-Test-User")
            if not uid:
                raise HTTPException(status_code=401, detail="Authentication required")
            return _profile_user(uid)

        app.dependency_overrides[get_current_user] = _user
    return app


URL = "/api/v1/finance/accounts"


def test_unauthenticated_request_is_rejected_by_real_auth(db_file, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "local")
    client = TestClient(_app(db_file, fake_auth=False))
    assert client.get(URL, params={"profile_id": "prof-1"}).status_code == 401


@pytest.mark.parametrize(
    ("user", "method", "expected"),
    [
        ("owner", "get", 200),
        ("owner", "post", 200),
        ("reader", "get", 200),
        ("reader", "post", 403),
        ("writer", "post", 200),
        ("expired", "get", 403),
        ("stranger", "get", 403),
    ],
)
def test_scope_matrix(db_file, user, method, expected) -> None:
    client = TestClient(_app(db_file))
    response = getattr(client, method)(URL, params={"profile_id": "prof-1"}, headers={"X-Test-User": user})
    assert response.status_code == expected, response.text
    if method == "post" and expected == 200:
        assert response.json()["level"] == "write"


def test_unknown_profile_and_missing_profile_id(db_file) -> None:
    client = TestClient(_app(db_file))
    assert client.get(URL, params={"profile_id": "nope"}, headers={"X-Test-User": "owner"}).status_code == 404
    assert client.get(URL, headers={"X-Test-User": "owner"}).status_code in (400, 422)


def test_pack_contribution_without_scope_cannot_be_mounted() -> None:
    with pytest.raises(PackRouterContractError):
        build_contribution_dependencies(RouterContribution(APIRouter(), prefix="/finance/x", pack_id="finance"))
    with pytest.raises(PackRouterContractError):
        build_contribution_dependencies(RouterContribution(APIRouter(), prefix="/finance/x"))


@pytest.mark.parametrize("prefix", ["/api/v1/finance/accounts", "api/finance", "/api"])
def test_pack_prefix_must_be_relative_to_api_root(prefix) -> None:
    with pytest.raises(PackRouterContractError):
        build_contribution_dependencies(
            RouterContribution(APIRouter(), prefix=prefix, pack_id="finance", scope="finance.accounts")
        )


def test_route_inventory_every_pack_route_is_guarded(db_file) -> None:
    app = _app(db_file)
    pack_routes = [r for r in iter_api_routes(app.routes) if r.path.startswith("/api/v1/finance")]
    assert pack_routes
    for route in pack_routes:
        assert route_scope_guards(route) == [("finance.accounts", "read", "finance")], route.path
