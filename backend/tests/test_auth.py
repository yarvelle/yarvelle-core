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

"""Unit tests for AuthPort, SqlAuthAdapter, and DisabledAuthAdapter."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yarvelle_core.auth.adapters.disabled_adapter import DisabledAuthAdapter
from yarvelle_core.auth.adapters.sql_adapter import SqlAuthAdapter
from yarvelle_core.auth.ports import RegisterUserRequest
from yarvelle_core.db.models import Base
from yarvelle_core.db.scoped_session import ScopedAsyncSession


@pytest.mark.asyncio
async def test_disabled_auth_adapter_returns_steward():
    adapter = DisabledAuthAdapter()
    session = await adapter.validate_session("dummy_token")
    assert session is not None
    assert session.username == "steward"


@pytest.mark.asyncio
async def test_sql_auth_adapter_lifecycle():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=ScopedAsyncSession, expire_on_commit=False)
    adapter = SqlAuthAdapter(session_factory=session_factory)

    # Register user
    req = RegisterUserRequest(
        email="user@yarvelle.local",
        username="testuser",
        password="SecureMasterPassword123!",
    )
    user = await adapter.register_user(req)
    assert user.username == "testuser"
    assert user.email == "user@yarvelle.local"

    # Authenticate user
    auth_result = await adapter.authenticate("testuser", "SecureMasterPassword123!")
    assert auth_result is not None
    assert auth_result.id == user.id

    # Create & validate session
    token = await adapter.create_session(user.id)
    val = await adapter.validate_session(token.token)
    assert val is not None
    assert val.id == user.id

    await engine.dispose()
