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

"""Pytest configuration and shared fixtures for yarvelle-core."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yarvelle_core.config import settings
import yarvelle_core.db.models as _all_models
from yarvelle_core.db.models import Base
from yarvelle_core.db.scoped_session import ScopedAsyncSession


@pytest.fixture(autouse=True)
def isolate_test_yarvelle_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Guarantees every pytest runs inside an isolated temporary directory."""
    test_home = tmp_path / ".yarvelle"
    test_home.mkdir(parents=True, exist_ok=True)
    (test_home / "data" / "files").mkdir(parents=True, exist_ok=True)
    (test_home / "logs").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("YARVELLE_HOME", str(test_home))
    monkeypatch.setenv("CAREFOLD_HOME", str(test_home))
    monkeypatch.setenv("YARVELLE_DATABASE_URL", f"sqlite+aiosqlite:///{test_home}/yarvelle.db")

    if hasattr(settings, "home_dir"):
        settings.home_dir = test_home
    settings.database_url = f"sqlite+aiosqlite:///{test_home}/yarvelle.db"
    settings.auth_provider = "disabled"

    yield test_home


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Provides a sandboxed workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "attachments").mkdir(parents=True, exist_ok=True)
    (ws / "notes").mkdir(parents=True, exist_ok=True)
    (ws / "skills").mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
async def async_db_session(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """Provides an isolated AsyncSession backed by an in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=ScopedAsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()
