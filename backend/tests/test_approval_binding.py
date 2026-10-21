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

"""Approvals are single-use and bound to the profile and tool they were issued for."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yarvelle_core.api.approvals import consume_approval_atomic
from yarvelle_core.engine.tool_exec import compute_payload_hash
from yarvelle_core.db.models import Approval, Profile
from yarvelle_core.engine.tool_exec import ToolContext, _consume_bound_approval, execute_tool_call
from yarvelle_core.engine.tool_registry import ToolSpec

ARGS = {"to": "school@example.test", "body": "hello"}


async def _seed(session, approval_id: str = "app-1", tool: str = "send_email", profile: str = "prof-a") -> None:
    for pid in ("prof-a", "prof-b"):
        if await session.get(Profile, pid) is None:
            session.add(Profile(id=pid, name=pid))
    await session.flush()
    now = datetime.now(timezone.utc)
    session.add(
        Approval(
            id=approval_id,
            profile_id=profile,
            run_id="run-1",
            tool_name=tool,
            args_redacted="{}",
            payload_hash=compute_payload_hash(ARGS),
            risk_tier="write_external",
            status="approved",
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
    )
    await session.commit()


async def _status(session, approval_id: str) -> str:
    session.expire_all()
    record = await session.get(Approval, approval_id)
    return record.status


@pytest.mark.asyncio
async def test_matching_binding_consumes_once(async_db_session) -> None:
    await _seed(async_db_session)
    assert await consume_approval_atomic(async_db_session, "app-1", ARGS, profile_id="prof-a", tool_name="send_email") == "app-1"
    assert await _status(async_db_session, "app-1") == "consumed"
    with pytest.raises(ValueError):
        await consume_approval_atomic(async_db_session, "app-1", ARGS, profile_id="prof-a", tool_name="send_email")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile_id", "tool_name", "fragment"),
    [("prof-b", "send_email", "different profile"), ("prof-a", "delete_everything", "different tool")],
)
async def test_mismatched_binding_is_rejected_and_not_consumed(async_db_session, profile_id, tool_name, fragment) -> None:
    await _seed(async_db_session)
    with pytest.raises(ValueError, match=fragment):
        await consume_approval_atomic(async_db_session, "app-1", ARGS, profile_id=profile_id, tool_name=tool_name)
    assert await _status(async_db_session, "app-1") == "approved"


class _LegacyStoreNoGet:
    def __init__(self) -> None:
        self.calls = 0

    async def consume_atomic(self, approval_id, current_args):
        self.calls += 1
        return approval_id


class _LegacyStoreWithGet(_LegacyStoreNoGet):
    def __init__(self, record) -> None:
        super().__init__()
        self._record = record

    async def get(self, approval_id):
        return self._record


@pytest.mark.asyncio
async def test_legacy_store_without_lookup_fails_closed() -> None:
    store = _LegacyStoreNoGet()
    with pytest.raises(PermissionError):
        await _consume_bound_approval(store, store.consume_atomic, "app-1", ARGS, "prof-a", "send_email")
    assert store.calls == 0


@pytest.mark.asyncio
async def test_legacy_store_binding_checked_via_get() -> None:
    wrong = _LegacyStoreWithGet(SimpleNamespace(profile_id="prof-b", tool_name="send_email"))
    with pytest.raises(ValueError):
        await _consume_bound_approval(wrong, wrong.consume_atomic, "app-1", ARGS, "prof-a", "send_email")
    assert wrong.calls == 0

    right = _LegacyStoreWithGet({"profile_id": "prof-a", "tool_name": "send_email"})
    await _consume_bound_approval(right, right.consume_atomic, "app-1", ARGS, "prof-a", "send_email")
    assert right.calls == 1


@pytest.mark.asyncio
async def test_choke_point_refuses_approval_from_other_profile() -> None:
    executed: list[dict] = []

    def _send(args):
        executed.append(args)
        return {"sent": True}

    spec = ToolSpec(name="send_email", risk_tier="irreversible", executor=_send)
    store = _LegacyStoreWithGet(SimpleNamespace(profile_id="prof-b", tool_name="send_email"))
    ctx = ToolContext(user_id="u-1", profile_id="prof-a", autonomy="A2")

    result = await execute_tool_call(ctx, spec, ARGS, approval_store=store, approval_id="app-1")

    assert not result.success
    assert "ApprovalResumeFailed" in (result.error or "")
    assert executed == []
