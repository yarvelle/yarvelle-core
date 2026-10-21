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

"""Regression tests for shared profile access resolution in api.deps."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yarvelle_core.api.deps import get_user_profile_access
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.config import settings
from yarvelle_core.db.models import Profile, ProfileAccess, User


def _user_profile(user_id: str) -> UserProfile:
    now = datetime.now(timezone.utc)
    return UserProfile(id=user_id, email=f"{user_id}@example.test", username=user_id, created_at=now, updated_at=now)


async def _seed(session) -> None:
    session.add_all(
        [
            User(id="owner-1", email="owner@example.test", username="owner", hashed_password="x"),
            User(id="viewer-1", email="viewer@example.test", username="viewer", hashed_password="x"),
            User(id="stranger-1", email="stranger@example.test", username="stranger", hashed_password="x"),
        ]
    )
    await session.flush()
    session.add(Profile(id="prof-1", name="Shared", user_id="owner-1"))
    await session.flush()
    session.add(ProfileAccess(profile_id="prof-1", user_id="viewer-1", access_level="view_paperwork"))
    await session.commit()


@pytest.mark.asyncio
async def test_shared_grant_resolves_without_name_error(async_db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "local")
    await _seed(async_db_session)
    profile = await async_db_session.get(Profile, "prof-1")

    assert await get_user_profile_access(profile, _user_profile("owner-1"), async_db_session) == "manage"
    assert await get_user_profile_access(profile, _user_profile("viewer-1"), async_db_session) == "view_paperwork"
    assert await get_user_profile_access(profile, _user_profile("stranger-1"), async_db_session) is None
