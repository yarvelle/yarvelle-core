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

"""Profile deletion must be atomic: DB purge (incl. DEK) commits before any file destruction."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from yarvelle_core.api import profiles as profiles_api
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.config import settings
from yarvelle_core.db.models import Note, Profile, ProfileKey, ScopeGrant
from yarvelle_core.scope.context import scope_context

PROFILE_ID = "prof-delete-1"


class _StubSearchIndex:
    def __init__(self) -> None:
        self.purged: list[str] = []

    async def purge_profile(self, profile_id: str) -> None:
        self.purged.append(profile_id)


class _StubMemoryPort:
    def __init__(self) -> None:
        self.forgotten: list[str] = []

    def forget_all(self, namespace: str) -> None:
        self.forgotten.append(namespace)


@pytest.fixture(autouse=True)
def stub_memory_port(monkeypatch) -> _StubMemoryPort:
    stub = _StubMemoryPort()
    monkeypatch.setattr(profiles_api, "get_memory_port", lambda: stub)
    search = _StubSearchIndex()
    monkeypatch.setattr("yarvelle_core.search.factory.get_search_index", lambda *a, **k: search)
    stub.search = search  # type: ignore[attr-defined]
    return stub


async def _seed(session) -> Path:
    session.add(Profile(id=PROFILE_ID, name="Secondary", is_primary=False))
    await session.flush()
    session.add_all(
        [
            ProfileKey(profile_id=PROFILE_ID, encrypted_dek="00" * 60),
            ScopeGrant(profile_id=PROFILE_ID, scope="finance.*", access_level="read"),
        ]
    )
    with scope_context(scope="health"):
        session.add(Note(profile_id=PROFILE_ID, slug="n1", title="Health note"))
        await session.flush()
    with scope_context(scope="finance", granted_scopes={"finance", "finance.*"}):
        session.add(Note(profile_id=PROFILE_ID, slug="n2", title="Finance note", scope="finance"))
        await session.flush()
    await session.commit()

    cas_dir = Path(settings.home_dir) / "data" / "files" / "default" / PROFILE_ID
    cas_dir.mkdir(parents=True, exist_ok=True)
    (cas_dir / "blob.bin").write_bytes(b"ciphertext")
    return cas_dir


async def _count(session, model) -> int:
    stmt = select(func.count()).select_from(model.__table__).where(model.__table__.c.profile_id == PROFILE_ID)
    return int((await session.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_delete_purges_rows_across_scopes_and_files(async_db_session, stub_memory_port) -> None:
    cas_dir = await _seed(async_db_session)

    result = await profiles_api.delete_profile(PROFILE_ID, DEFAULT_STEWARD_USER, async_db_session)

    assert result == {"deleted": True, "id": PROFILE_ID}
    assert await async_db_session.get(Profile, PROFILE_ID) is None
    for model in (ProfileKey, ScopeGrant, Note):
        assert await _count(async_db_session, model) == 0, model.__name__
    assert not cas_dir.exists()
    assert PROFILE_ID in stub_memory_port.forgotten
    assert stub_memory_port.search.purged == [PROFILE_ID]


@pytest.mark.asyncio
async def test_db_failure_leaves_keys_and_files_intact(async_db_session, monkeypatch, stub_memory_port) -> None:
    cas_dir = await _seed(async_db_session)

    async def _boom(db, profile_id):
        raise RuntimeError("simulated FK failure")

    monkeypatch.setattr(profiles_api, "purge_profile_rows", _boom)

    with pytest.raises(HTTPException) as exc_info:
        await profiles_api.delete_profile(PROFILE_ID, DEFAULT_STEWARD_USER, async_db_session)

    assert exc_info.value.status_code == 500
    assert "simulated" not in str(exc_info.value.detail)
    assert await async_db_session.get(Profile, PROFILE_ID) is not None
    assert await _count(async_db_session, ProfileKey) == 1
    assert (cas_dir / "blob.bin").is_file()
    assert stub_memory_port.forgotten == []
