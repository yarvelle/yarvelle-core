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

from pathlib import Path
import pytest

from yarvelle_core.config import settings
from yarvelle_core.testing.fixtures import (  # noqa: F401
    async_db_engine_and_factory,
    async_db_session,
    auth_client,
)


@pytest.fixture(autouse=True)
def isolate_test_yarvelle_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Guarantees every pytest runs inside an isolated temporary directory."""
    test_home = tmp_path / ".yarvelle"
    test_home.mkdir(parents=True, exist_ok=True)
    (test_home / "data" / "files").mkdir(parents=True, exist_ok=True)
    (test_home / "logs").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("YARVELLE_HOME", str(test_home))
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
