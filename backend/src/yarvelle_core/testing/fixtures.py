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

"""Reusable async database, entity, and HTTP client factories for test suites.

Opt-in test helpers exported by ``yarvelle_core.testing.fixtures`` so both core
and pack test suites can spin up isolated in-memory SQLite engines, seed
``User`` / ``Profile`` / ``Connection`` / ``SyncRun`` rows, open authenticated
ASGI test clients, and assert SQL statement counts without copy-pasting setup.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import itertools
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple
import uuid

import pytest


_SEQ = itertools.count(1)


def _next_seq() -> int:
    return next(_SEQ)


@asynccontextmanager
async def create_test_session_factory(
    database_url: str = "sqlite+aiosqlite:///:memory:",
    *,
    session_class: Optional[Any] = None,
    create_tables: bool = True,
    echo: bool = False,
) -> AsyncIterator[Tuple[Any, Any]]:
    """Create an isolated async SQLAlchemy engine + sessionmaker and dispose on exit."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import yarvelle_core.db.models as _all_models  # noqa: F401
    from yarvelle_core.db.models import Base
    from yarvelle_core.db.scoped_session import ScopedAsyncSession

    effective_cls = session_class if session_class is not None else ScopedAsyncSession
    engine = create_async_engine(database_url, future=True, echo=echo)
    try:
        if create_tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=effective_cls,
        )
        yield engine, factory
    finally:
        await engine.dispose()


@asynccontextmanager
async def create_auth_client(
    session_factory: Any,
    *,
    user: Optional[Any] = None,
    prefix: str = "/api/v1",
    router: Optional[Any] = None,
    base_url: str = "http://testserver",
) -> AsyncIterator[Any]:
    """Yield an authenticated ``httpx.AsyncClient`` bound to a FastAPI test app."""
    from fastapi import FastAPI
    import httpx

    from yarvelle_core.api.deps import get_current_user, get_db
    from yarvelle_core.api.router import api_router
    from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER

    effective_user = user if user is not None else DEFAULT_STEWARD_USER
    effective_router = router if router is not None else api_router

    app = FastAPI()
    app.include_router(effective_router, prefix=prefix)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    def _override_get_user():
        return effective_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        client.app = app  # type: ignore[attr-defined]
        client.session_factory = session_factory  # type: ignore[attr-defined]
        yield client


class SQLStatementCounter:
    """SQLAlchemy ``before_cursor_execute`` and ``commit`` counter for query-budget tests."""

    def __init__(self) -> None:
        self.statements: List[str] = []
        self.commits: int = 0

    @property
    def total(self) -> int:
        return len(self.statements)

    @property
    def selects(self) -> List[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]

    @property
    def writes(self) -> List[str]:
        prefixes = ("INSERT", "UPDATE", "DELETE", "REPLACE")
        return [
            s
            for s in self.statements
            if s.lstrip().upper().startswith(prefixes)
        ]

    def reset(self) -> None:
        self.statements.clear()
        self.commits = 0


@contextmanager
def count_sql_statements(engine: Any) -> Iterator[SQLStatementCounter]:
    """Record SQL statements and commits executed against ``engine`` inside the block."""
    from sqlalchemy import event

    sync_engine = getattr(engine, "sync_engine", engine)
    counter = SQLStatementCounter()

    def _on_execute(_conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool) -> None:
        stripped = statement.strip()
        upper = stripped.upper()
        if upper.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "PRAGMA", "BEGIN")):
            return
        counter.statements.append(stripped)

    def _on_commit(_conn: Any) -> None:
        counter.commits += 1

    event.listen(sync_engine, "before_cursor_execute", _on_execute)
    event.listen(sync_engine, "commit", _on_commit)
    try:
        yield counter
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)
        event.remove(sync_engine, "commit", _on_commit)


class UserFactory:
    """Factory for ``User`` ORM rows and ``UserProfile`` auth principals."""

    @classmethod
    def build(
        cls,
        *,
        id: Optional[str] = None,
        username: Optional[str] = None,
        email: Optional[str] = None,
        hashed_password: str = "not-a-real-hash",
        full_name: Optional[str] = "Test Steward",
        role: str = "steward",
        status: str = "active",
        auth_provider: str = "local",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> Any:
        from yarvelle_core.db.models import User

        seq = _next_seq()
        now = created_at or datetime.now(timezone.utc)
        uname = username or f"user_{seq}"
        return User(
            id=id or str(uuid.uuid4()),
            username=uname,
            email=email or f"{uname}@yarvelle.local",
            hashed_password=hashed_password,
            full_name=full_name,
            role=role,
            status=status,
            auth_provider=auth_provider,
            created_at=now,
            updated_at=updated_at or now,
        )

    @classmethod
    def build_principal(
        cls,
        *,
        id: Optional[str] = None,
        username: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "steward",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> Any:
        from yarvelle_core.auth.ports import UserProfile

        seq = _next_seq()
        now = created_at or datetime.now(timezone.utc)
        uname = username or f"user_{seq}"
        return UserProfile(
            id=id or str(uuid.uuid4()),
            username=uname,
            email=email or f"{uname}@yarvelle.local",
            role=role,
            created_at=now,
            updated_at=updated_at or now,
        )

    @classmethod
    async def create(cls, session: Any, **kwargs: Any) -> Any:
        user = cls.build(**kwargs)
        session.add(user)
        await session.flush()
        return user


class ProfileFactory:
    """Factory for ``Profile`` ORM rows."""

    @classmethod
    def build(
        cls,
        *,
        id: Optional[str] = None,
        user_id: Optional[str] = None,
        name: Optional[str] = None,
        relationship: str = "self",
        role: str = "self",
        date_of_birth: Optional[str] = "1990-01-15",
        avatar_color: str = "indigo",
        is_primary: bool = True,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> Any:
        from yarvelle_core.db.models import Profile

        seq = _next_seq()
        now = created_at or datetime.now(timezone.utc)
        return Profile(
            id=id or str(uuid.uuid4()),
            user_id=user_id,
            name=name or f"Profile {seq}",
            relationship=relationship,
            role=role,
            date_of_birth=date_of_birth,
            avatar_color=avatar_color,
            is_primary=is_primary,
            created_at=now,
            updated_at=updated_at or now,
        )

    @classmethod
    async def create(cls, session: Any, **kwargs: Any) -> Any:
        profile = cls.build(**kwargs)
        session.add(profile)
        await session.flush()
        return profile


class ConnectionFactory:
    """Factory for ``Connection`` and ``SyncRun`` ORM rows."""

    @classmethod
    def build(
        cls,
        *,
        id: Optional[str] = None,
        user_id: str,
        profile_id: str,
        connector_id: str = "google-calendar",
        status: str = "active",
        label: Optional[str] = None,
        config_json: str = "{}",
        consecutive_failures: int = 0,
        last_sync_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> Any:
        from yarvelle_core.db.models import Connection

        seq = _next_seq()
        now = created_at or datetime.now(timezone.utc)
        return Connection(
            id=id or str(uuid.uuid4()),
            user_id=user_id,
            profile_id=profile_id,
            connector_id=connector_id,
            status=status,
            label=label or f"Connector {seq}",
            config_json=config_json,
            consecutive_failures=consecutive_failures,
            last_sync_at=last_sync_at,
            created_at=now,
            updated_at=updated_at or now,
        )

    @classmethod
    async def create(cls, session: Any, **kwargs: Any) -> Any:
        connection = cls.build(**kwargs)
        session.add(connection)
        await session.flush()
        return connection

    @classmethod
    async def create_sync_run(
        cls,
        session: Any,
        *,
        connection: Any,
        id: Optional[str] = None,
        stream: str = "events",
        status: str = "succeeded",
        records_fetched: int = 5,
        records_upserted: int = 5,
        records_quarantined: int = 0,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[int] = 42,
    ) -> Any:
        from yarvelle_core.db.models import SyncRun

        now = started_at or datetime.now(timezone.utc)
        run = SyncRun(
            id=id or str(uuid.uuid4()),
            connection_id=connection.id,
            profile_id=connection.profile_id,
            connector_id=connection.connector_id,
            stream=stream,
            status=status,
            records_fetched=records_fetched,
            records_upserted=records_upserted,
            records_quarantined=records_quarantined,
            error_code=error_code,
            error_message=error_message,
            started_at=now,
            completed_at=completed_at or now,
            duration_ms=duration_ms,
            created_at=now,
        )
        session.add(run)
        await session.flush()
        return run


@pytest.fixture
async def async_db_engine_and_factory() -> AsyncIterator[Tuple[Any, Any]]:
    """Pytest fixture yielding ``(engine, session_factory)`` backed by in-memory SQLite."""
    async with create_test_session_factory() as pair:
        yield pair


@pytest.fixture
async def async_db_session(async_db_engine_and_factory: Tuple[Any, Any]) -> AsyncIterator[Any]:
    """Pytest fixture yielding an isolated ``ScopedAsyncSession``."""
    _engine, session_factory = async_db_engine_and_factory
    async with session_factory() as session:
        yield session


@pytest.fixture
async def auth_client(async_db_engine_and_factory: Tuple[Any, Any]) -> AsyncIterator[Any]:
    """Pytest fixture yielding an authenticated ``httpx.AsyncClient`` sharing ``async_db_session``'s DB."""
    engine, session_factory = async_db_engine_and_factory
    async with create_auth_client(session_factory) as client:
        client.engine = engine  # type: ignore[attr-defined]
        yield client


__all__ = [
    "ConnectionFactory",
    "ProfileFactory",
    "SQLStatementCounter",
    "UserFactory",
    "async_db_engine_and_factory",
    "async_db_session",
    "auth_client",
    "count_sql_statements",
    "create_auth_client",
    "create_test_session_factory",
]
