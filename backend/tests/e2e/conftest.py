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

"""Shared fixtures and configuration for Yarvelle Core E2E test suites."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Tuple
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.db.base import Base
import yarvelle_core.db.models  # noqa: F401
from yarvelle_core.db.models import Profile, User
from yarvelle_core.db.scoped_session import ScopedAsyncSession
from yarvelle_core.db.session import create_db_engine
from yarvelle_core.scope.context import DEFAULT_SCOPE, scope_context
from yarvelle_core.testing.fixtures import (  # noqa: F401
    ProfileFactory,
    UserFactory,
    async_db_engine_and_factory,
    async_db_session,
    auth_client,
    create_auth_client,
    create_test_session_factory,
)


@pytest.fixture
def e2e_workspace(tmp_path: Path) -> Path:
    """Provides a sandboxed workspace directory for E2E tests."""
    ws = tmp_path / "e2e_workspace"
    (ws / "attachments").mkdir(parents=True, exist_ok=True)
    (ws / "notes").mkdir(parents=True, exist_ok=True)
    (ws / "skills").mkdir(parents=True, exist_ok=True)
    (ws / "agents").mkdir(parents=True, exist_ok=True)
    (ws / "logs").mkdir(parents=True, exist_ok=True)
    return ws


@pytest_asyncio.fixture
async def e2e_db_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[ScopedAsyncSession]]:
    """Provides an isolated database session factory with schema initialized."""
    from yarvelle_core.config import settings

    db_path = tmp_path / "e2e_runtime.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setenv("YARVELLE_DATABASE_URL", db_url)

    engine = create_db_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=ScopedAsyncSession)

    import yarvelle_core.db.session as db_session_mod
    import yarvelle_core.tools.mcp_db_toolbox as toolbox_mod

    monkeypatch.setattr(db_session_mod, "_engine", engine, raising=False)
    monkeypatch.setattr(db_session_mod, "_session_factory", factory, raising=False)
    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda *a, **k: factory)
    monkeypatch.setattr(toolbox_mod, "get_session_factory", lambda *a, **k: factory)

    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def e2e_steward_context(
    e2e_db_factory: async_sessionmaker[ScopedAsyncSession],
) -> AsyncIterator[Tuple[User, Profile]]:
    """Seeds a test steward user and primary profile."""
    async with e2e_db_factory() as session:
        user = UserFactory.build(
            id=DEFAULT_STEWARD_USER.id,
            username="steward",
            email="steward@yarvelle.local",
            role="steward",
            status="active",
            auth_provider="disabled",
            hashed_password="test-hashed-password",
        )
        session.add(user)
        await session.flush()

        profile = Profile(
            id="prof-steward-e2e",
            user_id=user.id,
            name="Primary Steward Profile",
            relationship="self",
            role="self",
            date_of_birth="1990-01-01",
            avatar_color="indigo",
            is_primary=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(profile)
        await session.commit()

        yield user, profile


@pytest_asyncio.fixture
async def e2e_scoped_session(
    e2e_db_factory: async_sessionmaker[ScopedAsyncSession],
    e2e_steward_context: Tuple[User, Profile],
) -> AsyncIterator[ScopedAsyncSession]:
    """Yields a database session pre-bound to the steward profile and default scope."""
    _user, profile = e2e_steward_context
    with scope_context(profile_id=profile.id, scope=DEFAULT_SCOPE):
        async with e2e_db_factory() as session:
            yield session


@pytest_asyncio.fixture
async def e2e_auth_client(
    e2e_db_factory: async_sessionmaker[ScopedAsyncSession],
    e2e_steward_context: Tuple[User, Profile],
) -> AsyncIterator[Any]:
    """Provides an authenticated test HTTP client for API router testing."""
    async with create_auth_client(session_factory=e2e_db_factory) as client:
        yield client
