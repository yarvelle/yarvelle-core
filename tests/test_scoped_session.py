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

"""Unit tests for ScopeContext, ScopedMixin, and ScopedSession ORM interception."""

from __future__ import annotations

import uuid
import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from yarvelle_core.db.models import Base
from yarvelle_core.db.scoped_session import ScopedAsyncSession
from yarvelle_core.scope.context import ScopeViolationError, scope_context
from yarvelle_core.scope.mixin import ScopedMixin


class TestScopedEntity(Base, ScopedMixin):
    __test__ = False
    __tablename__ = "test_scoped_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


@pytest.mark.asyncio
async def test_scoped_session_select_filtering():
    """Assert ScopedSession automatically injects scope criteria on SELECT."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=ScopedAsyncSession, expire_on_commit=False)

    pid = str(uuid.uuid4())
    async with factory() as session:
        # Seed record under scope 'alpha.records'
        with scope_context(scope="alpha.records", profile_id=pid, pack_id="alpha", granted_scopes={"alpha.*"}, pack_declared_scopes={"alpha.*"}):
            e1 = TestScopedEntity(id="e1", profile_id=pid, scope="alpha.records", name="Alpha Doc")
            session.add(e1)
            await session.commit()

        # Seed record under scope 'beta.records'
        with scope_context(scope="beta.records", profile_id=pid, pack_id="beta", granted_scopes={"beta.*"}, pack_declared_scopes={"beta.*"}):
            e2 = TestScopedEntity(id="e2", profile_id=pid, scope="beta.records", name="Beta Doc")
            session.add(e2)
            await session.commit()

        # Query with alpha grant -> only e1 returned
        with scope_context(scope="alpha.records", profile_id=pid, pack_id="alpha", granted_scopes={"alpha.*"}, pack_declared_scopes={"alpha.*"}):
            res = await session.execute(select(TestScopedEntity).where(TestScopedEntity.profile_id == pid))
            rows = list(res.scalars().all())
            assert len(rows) == 1
            assert rows[0].id == "e1"

        # Query with beta grant -> only e2 returned
        with scope_context(scope="beta.records", profile_id=pid, pack_id="beta", granted_scopes={"beta.*"}, pack_declared_scopes={"beta.*"}):
            res = await session.execute(select(TestScopedEntity).where(TestScopedEntity.profile_id == pid))
            rows = list(res.scalars().all())
            assert len(rows) == 1
            assert rows[0].id == "e2"

    await engine.dispose()


@pytest.mark.asyncio
async def test_scoped_session_before_flush_write_guard():
    """Assert ScopedSession rejects flushing entity whose scope is not owned by active pack."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=ScopedAsyncSession, expire_on_commit=False)
    pid = str(uuid.uuid4())

    async with factory() as session:
        # Pack 'alpha' attempts to insert record with scope 'beta.unauthorized'
        with scope_context(scope="alpha.main", profile_id=pid, pack_id="alpha", granted_scopes={"alpha.*"}, pack_declared_scopes={"alpha.*"}):
            bad_entity = TestScopedEntity(id="bad_1", profile_id=pid, scope="beta.unauthorized", name="Tampered")
            session.add(bad_entity)
            with pytest.raises(ScopeViolationError) as exc_info:
                await session.flush()
            assert "not permitted in active granted scopes" in str(exc_info.value)

    await engine.dispose()
