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

"""Approval records and approval events carry redacted tool arguments."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request

from yarvelle_core.api.approvals import ApprovalDecideRequest, decide_approval
from yarvelle_core.audit.redaction import (
    REDACTED_PLACEHOLDER,
    contains_redaction_placeholder,
    redact_tool_args,
)
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.config import settings
from yarvelle_core.db.models import Approval, Profile
from yarvelle_core.engine.tool_exec import SqlApprovalStore, compute_payload_hash

ARGS = {
    "to": "clinic@example.test",
    "api_key": "sk-live-0123456789abcdefghij",
    "auth": {"Password": "hunter2", "username": "sam"},
    "body": "Use header Authorization: Bearer abcdefghijklmnop1234 please",
    "max_tokens": 256,
    "footprint": "small",
    "attachments": [{"refresh_token": "r-1"}],
}


def test_redact_tool_args_masks_secrets_without_mutating_input() -> None:
    original = json.loads(json.dumps(ARGS))
    red = redact_tool_args(ARGS)
    assert ARGS == original
    assert red["api_key"] == REDACTED_PLACEHOLDER
    assert red["auth"] == REDACTED_PLACEHOLDER
    assert red["attachments"][0]["refresh_token"] == REDACTED_PLACEHOLDER
    assert "abcdefghijklmnop1234" not in red["body"] and REDACTED_PLACEHOLDER in red["body"]
    assert red["to"] == "clinic@example.test"
    assert red["max_tokens"] == 256
    assert red["footprint"] == "small"
    assert contains_redaction_placeholder(red) and not contains_redaction_placeholder(ARGS)


@pytest.mark.asyncio
async def test_sql_store_persists_redacted_args_but_hashes_real_payload(async_db_session) -> None:
    async_db_session.add(Profile(id="prof-a", name="A"))
    await async_db_session.commit()
    store = SqlApprovalStore(async_sessionmaker(async_db_session.bind, expire_on_commit=False))
    await store.create_pending("app-1", "prof-a", "run-1", "send_email", ARGS, "write_external")

    async_db_session.expire_all()
    record = await async_db_session.get(Approval, "app-1")
    stored = json.loads(record.args_redacted)
    assert "sk-live-0123456789abcdefghij" not in record.args_redacted
    assert "hunter2" not in record.args_redacted
    assert stored["api_key"] == REDACTED_PLACEHOLDER
    assert record.payload_hash == compute_payload_hash(ARGS)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""})


async def _seed_pending(session) -> None:
    session.add(Profile(id="prof-a", name="A"))
    await session.flush()
    now = datetime.now(timezone.utc)
    session.add(
        Approval(
            id="app-2",
            profile_id="prof-a",
            run_id="run-1",
            tool_name="send_email",
            args_redacted=json.dumps(redact_tool_args(ARGS)),
            payload_hash=compute_payload_hash(ARGS),
            risk_tier="write_external",
            status="pending",
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_decide_rejects_edits_that_still_contain_placeholders(async_db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "disabled")
    await _seed_pending(async_db_session)
    payload = ApprovalDecideRequest(decision="approved", edited_args=redact_tool_args(ARGS))
    with pytest.raises(HTTPException) as exc:
        await decide_approval("app-2", payload, _request(), DEFAULT_STEWARD_USER, async_db_session)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_decide_with_full_edits_stores_redacted_copy(async_db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "disabled")
    await _seed_pending(async_db_session)
    edited = dict(ARGS, to="other@example.test")
    payload = ApprovalDecideRequest(decision="approved", edited_args=edited)
    await decide_approval("app-2", payload, _request(), DEFAULT_STEWARD_USER, async_db_session)
    async_db_session.expire_all()
    record = await async_db_session.get(Approval, "app-2")
    assert record.payload_hash == compute_payload_hash(edited)
    assert "hunter2" not in record.args_redacted
    assert json.loads(record.args_redacted)["to"] == "other@example.test"
