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

"""Regression tests for issue #53 bounded queries, read-only GETs, and streaming audit verification."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, List
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine.result import ScalarResult

from yarvelle_core.api.connections import list_profile_connections
from yarvelle_core.audit.hash_chain import (
    GENESIS_HASH,
    append_chained_audit_event,
    compute_audit_entry_hash,
    verify_profile_audit_chain,
)
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.db.models import AuditEventRecord, Job, Reminder
from yarvelle_core.engine.job_runner import JobRunner, sweep_overdue_reminders
from yarvelle_core.testing import (
    ConnectionFactory,
    ProfileFactory,
    SQLStatementCounter,
    UserFactory,
    async_db_engine_and_factory,
    async_db_session,
    auth_client,
    count_sql_statements,
    create_auth_client,
    create_test_session_factory,
)
from yarvelle_core.testing.orch_eval import judge as orch_judge
from yarvelle_core.testing.orch_eval import ollama_backend


@pytest.mark.asyncio
async def test_get_reminders_is_strictly_read_only_even_with_overdue_rows(
    async_db_session: Any,
    auth_client: Any,
) -> None:
    """GET /profiles/{profile_id}/reminders executes zero writes or commits even with overdue rows."""
    now = datetime.now(timezone.utc)
    steward = await UserFactory.create(
        async_db_session,
        id=DEFAULT_STEWARD_USER.id,
        username=DEFAULT_STEWARD_USER.username,
        email=DEFAULT_STEWARD_USER.email,
    )
    profile = await ProfileFactory.create(async_db_session, user_id=steward.id, name="Household Alpha")
    profile_id = profile.id

    overdue_due = now - timedelta(hours=36)
    upcoming_due = now + timedelta(hours=6)

    for idx in range(5):
        rem = Reminder(
            profile_id=profile.id,
            title=f"Overdue Pending {idx}",
            category="task",
            next_due_at=overdue_due,
            status="pending",
        )
        async_db_session.add(rem)
        await async_db_session.flush()
        async_db_session.add(
            Job(
                profile_id=profile.id,
                kind="reminder",
                next_run_at=overdue_due,
                status="pending",
                idempotency_key=f"reminder:{rem.id}",
            )
        )

    for idx in range(3):
        rem = Reminder(
            profile_id=profile.id,
            title=f"Overdue Snoozed {idx}",
            category="prep",
            next_due_at=overdue_due - timedelta(hours=4),
            snooze_until=overdue_due,
            status="snoozed",
        )
        async_db_session.add(rem)
        await async_db_session.flush()
        async_db_session.add(
            Job(
                profile_id=profile.id,
                kind="reminder",
                next_run_at=overdue_due,
                status="pending",
                idempotency_key=f"reminder:{rem.id}",
            )
        )

    for idx in range(2):
        rem = Reminder(
            profile_id=profile.id,
            title=f"Upcoming Task {idx}",
            category="general",
            next_due_at=upcoming_due,
            status="pending",
        )
        async_db_session.add(rem)
        await async_db_session.flush()
        async_db_session.add(
            Job(
                profile_id=profile.id,
                kind="reminder",
                next_run_at=upcoming_due,
                status="pending",
                idempotency_key=f"reminder:{rem.id}",
            )
        )

    await async_db_session.commit()

    with count_sql_statements(auth_client.engine) as counter:
        resp = await auth_client.get(f"/api/v1/profiles/{profile_id}/reminders")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 10
    assert len(body["reminders"]) == 10
    assert counter.writes == []
    assert counter.commits == 0

    # Verify overdue rows were NOT mutated by GET
    async_db_session.expire_all()
    statuses = list(
        (
            await async_db_session.execute(
                select(Reminder.status).where(Reminder.profile_id == profile_id)
            )
        ).scalars()
    )
    assert statuses.count("missed") == 0
    assert statuses.count("pending") == 7
    assert statuses.count("snoozed") == 3


@pytest.mark.asyncio
async def test_sweep_overdue_reminders_uses_two_set_based_updates_and_job_runner() -> None:
    """Background overdue sweep transitions reminders and jobs in exactly 2 set-based UPDATEs."""
    now = datetime.now(timezone.utc)
    overdue_due = now - timedelta(hours=30)
    upcoming_due = now + timedelta(hours=4)

    async with create_test_session_factory() as (engine, session_factory):
        async with session_factory() as session:
            steward = await UserFactory.create(session)
            profile = await ProfileFactory.create(session, user_id=steward.id)

            overdue_rem_ids: List[str] = []
            active_rem_ids: List[str] = []

            for idx in range(6):
                rem = Reminder(
                    profile_id=profile.id,
                    title=f"Pending Overdue {idx}",
                    next_due_at=overdue_due,
                    status="pending",
                )
                session.add(rem)
                await session.flush()
                overdue_rem_ids.append(rem.id)
                session.add(
                    Job(
                        profile_id=profile.id,
                        kind="reminder",
                        next_run_at=overdue_due,
                        status="pending",
                        idempotency_key=f"reminder:{rem.id}",
                    )
                )

            # Snoozed overdue reminders whose Job.next_run_at is still in the future:
            # proves missed_keys_subq links jobs via 'reminder:' || Reminder.id
            for idx in range(4):
                rem = Reminder(
                    profile_id=profile.id,
                    title=f"Snoozed Overdue {idx}",
                    next_due_at=overdue_due - timedelta(hours=2),
                    snooze_until=overdue_due,
                    status="snoozed",
                )
                session.add(rem)
                await session.flush()
                overdue_rem_ids.append(rem.id)
                session.add(
                    Job(
                        profile_id=profile.id,
                        kind="reminder",
                        next_run_at=upcoming_due,
                        status="pending",
                        idempotency_key=f"reminder:{rem.id}",
                    )
                )

            for idx in range(3):
                rem = Reminder(
                    profile_id=profile.id,
                    title=f"Active Upcoming {idx}",
                    next_due_at=upcoming_due,
                    status="pending",
                )
                session.add(rem)
                await session.flush()
                active_rem_ids.append(rem.id)
                session.add(
                    Job(
                        profile_id=profile.id,
                        kind="reminder",
                        next_run_at=upcoming_due,
                        status="pending",
                        idempotency_key=f"reminder:{rem.id}",
                    )
                )

            await session.commit()

        async with session_factory() as sweep_session:
            with count_sql_statements(engine) as counter:
                swept = await sweep_overdue_reminders(sweep_session, now_utc=now)
                await sweep_session.commit()

        assert swept == 10
        assert counter.selects == []
        assert len(counter.writes) == 2
        assert all(stmt.upper().startswith("UPDATE") for stmt in counter.writes)

        async with session_factory() as check_session:
            overdue_rems = list(
                (
                    await check_session.execute(
                        select(Reminder).where(Reminder.id.in_(overdue_rem_ids))
                    )
                ).scalars()
            )
            assert len(overdue_rems) == 10
            assert all(r.status == "missed" for r in overdue_rems)

            overdue_jobs = list(
                (
                    await check_session.execute(
                        select(Job).where(
                            Job.idempotency_key.in_([f"reminder:{rid}" for rid in overdue_rem_ids])
                        )
                    )
                ).scalars()
            )
            assert len(overdue_jobs) == 10
            assert all(j.status == "missed" for j in overdue_jobs)

            active_rems = list(
                (
                    await check_session.execute(
                        select(Reminder).where(Reminder.id.in_(active_rem_ids))
                    )
                ).scalars()
            )
            assert all(r.status == "pending" for r in active_rems)

            # Seed one more overdue reminder + job and verify JobRunner._sweep_overdue_reminders
            extra_rem = Reminder(
                profile_id=profile.id,
                title="Runner Sweep Target",
                next_due_at=overdue_due,
                status="pending",
            )
            check_session.add(extra_rem)
            await check_session.flush()
            check_session.add(
                Job(
                    profile_id=profile.id,
                    kind="reminder",
                    next_run_at=overdue_due,
                    status="pending",
                    idempotency_key=f"reminder:{extra_rem.id}",
                )
            )
            await check_session.commit()

        runner = JobRunner(session_factory=session_factory)
        runner_swept = await runner._sweep_overdue_reminders(now.timestamp())
        assert runner_swept == 1

        async with session_factory() as verify_runner_session:
            refreshed = await verify_runner_session.get(Reminder, extra_rem.id)
            assert refreshed is not None and refreshed.status == "missed"


@pytest.mark.asyncio
async def test_list_profile_connections_executes_constant_queries_with_twelve_connections() -> None:
    """list_profile_connections executes <= 2 SQL queries regardless of connection count."""
    base_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    async with create_test_session_factory() as (engine, session_factory):
        async with session_factory() as seed_session:
            steward = await UserFactory.create(
                seed_session,
                id=DEFAULT_STEWARD_USER.id,
                username=DEFAULT_STEWARD_USER.username,
                email=DEFAULT_STEWARD_USER.email,
            )
            empty_profile = await ProfileFactory.create(
                seed_session, user_id=steward.id, name="Empty Connections"
            )
            one_conn_profile = await ProfileFactory.create(
                seed_session, user_id=steward.id, name="Single Connection", is_primary=False
            )
            many_conn_profile = await ProfileFactory.create(
                seed_session, user_id=steward.id, name="Twelve Connections", is_primary=False
            )

            single_conn = await ConnectionFactory.create(
                seed_session,
                user_id=steward.id,
                profile_id=one_conn_profile.id,
                label="Single Calendar",
            )
            await ConnectionFactory.create_sync_run(
                seed_session,
                connection=single_conn,
                started_at=base_time,
                records_upserted=11,
            )

            expected_latest_upserted = {}
            for idx in range(12):
                conn = await ConnectionFactory.create(
                    seed_session,
                    user_id=steward.id,
                    profile_id=many_conn_profile.id,
                    label=f"Workspace Connector {idx:02d}",
                    created_at=base_time + timedelta(minutes=idx),
                )
                if idx < 10:
                    for run_idx in range(3):
                        upserted = (idx + 1) * 100 + run_idx
                        await ConnectionFactory.create_sync_run(
                            seed_session,
                            connection=conn,
                            started_at=base_time + timedelta(hours=run_idx),
                            records_upserted=upserted,
                        )
                    expected_latest_upserted[conn.id] = (idx + 1) * 100 + 2
                else:
                    expected_latest_upserted[conn.id] = None

            await seed_session.commit()

        # 1. Direct handler query-budget check: <= 2 SQL statements for 12 connections (30 SyncRuns)
        async with session_factory() as read_session:
            with count_sql_statements(engine) as many_counter:
                many_payload = await list_profile_connections(
                    profile_id=many_conn_profile.id,
                    profile=many_conn_profile,
                    db=read_session,
                )

        assert many_counter.total == 2
        assert many_counter.total <= 2
        assert many_counter.writes == []
        assert many_counter.commits == 0
        assert many_payload["total"] == 12
        assert many_payload["connections"] == many_payload["items"]

        for item in many_payload["connections"]:
            expected = expected_latest_upserted[item["id"]]
            if expected is None:
                assert item["latest_sync_run"] is None
            else:
                assert item["latest_sync_run"] is not None
                assert item["latest_sync_run"]["records_upserted"] == expected

        # Empty profile executes just 1 SELECT (and skips SyncRun window query)
        async with session_factory() as empty_session:
            with count_sql_statements(engine) as empty_counter:
                empty_payload = await list_profile_connections(
                    profile_id=empty_profile.id,
                    profile=empty_profile,
                    db=empty_session,
                )
        assert empty_counter.total == 1
        assert empty_payload["total"] == 0

        # 2. Full HTTP endpoint check: 1 connection vs 12 connections execute identical constant queries
        async with create_auth_client(session_factory) as client:
            with count_sql_statements(engine) as http_one_counter:
                r1 = await client.get(f"/api/v1/profiles/{one_conn_profile.id}/connections")
            with count_sql_statements(engine) as http_many_counter:
                r12 = await client.get(f"/api/v1/profiles/{many_conn_profile.id}/connections")

        assert r1.status_code == 200
        assert r12.status_code == 200
        assert r1.json()["total"] == 1
        assert r12.json()["total"] == 12
        assert http_one_counter.total == http_many_counter.total
        assert http_many_counter.writes == []


@pytest.mark.asyncio
async def test_verify_profile_audit_chain_streams_bounded_keyset_pages() -> None:
    """verify_profile_audit_chain streams keyset pages with LIMIT without calling .scalars().all()."""
    async with create_test_session_factory() as (engine, session_factory):
        profile_id = "profile_paged_audit_ok"
        events: List[AuditEventRecord] = []

        async with session_factory() as session:
            for idx in range(25):
                rec = await append_chained_audit_event(
                    session,
                    profile_id=profile_id,
                    actor_user_id="user_1",
                    principal="agent",
                    event="tool",
                    tool=f"tool_{idx:02d}",
                    risk="read",
                    decision="allow",
                    payload_hash=f"{idx:064x}",
                    scope="alpha.records",
                    pack_id="alpha",
                    risk_tier="read",
                )
                events.append(rec)
            await session.commit()

        def _forbid_scalars_all(_self: Any) -> Any:
            raise AssertionError("verify_profile_audit_chain must not call .scalars().all()")

        async with session_factory() as verify_session:
            with patch.object(ScalarResult, "all", _forbid_scalars_all):
                with count_sql_statements(engine) as counter:
                    result = await verify_profile_audit_chain(
                        verify_session,
                        profile_id,
                        batch_size=7,
                    )

        assert result["valid"] is True
        assert result["checked_count"] == 25
        assert result["head_hash"] == events[-1].entry_hash
        assert result["broken_at_event_id"] is None
        # ceil(25 / 7) == 4 bounded SELECT statements (7 + 7 + 7 + 4 -> <7 terminates loop)
        assert len(counter.selects) == 4
        assert all("LIMIT" in stmt.upper() for stmt in counter.selects)


@pytest.mark.asyncio
async def test_verify_profile_audit_chain_tie_breaker_and_cross_page_tamper_detection() -> None:
    """Keyset paging handles identical timestamps and detects broken links across page boundaries."""
    async with create_test_session_factory() as (engine, session_factory):
        profile_id = "profile_paged_audit_tamper"
        shared_ts = datetime(2026, 7, 10, 8, 30, 0, tzinfo=timezone.utc)
        event_ids = [f"evt-{idx:03d}" for idx in range(18)]

        async with session_factory() as session:
            prev_hash = GENESIS_HASH
            for idx, ev_id in enumerate(event_ids):
                # Events 4 and 5 share the exact same timestamp across the batch_size=5 page boundary!
                row_ts = shared_ts if idx in (4, 5) else shared_ts + timedelta(seconds=(idx if idx < 4 else idx - 1))
                if idx < 4:
                    row_ts = shared_ts - timedelta(seconds=(10 - idx))
                entry_hash = compute_audit_entry_hash(
                    prev_hash=prev_hash,
                    event_id=ev_id,
                    profile_id=profile_id,
                    event="tool",
                    tool=f"op_{idx}",
                    risk="read",
                    decision="allow",
                    payload_hash=f"{idx:064x}",
                    scope="alpha.records",
                    pack_id="alpha",
                    risk_tier="read",
                )
                session.add(
                    AuditEventRecord(
                        id=ev_id,
                        ts=row_ts,
                        profile_id=profile_id,
                        event="tool",
                        tool=f"op_{idx}",
                        risk="read",
                        decision="allow",
                        payload_hash=f"{idx:064x}",
                        prev_hash=prev_hash,
                        entry_hash=entry_hash,
                        scope="alpha.records",
                        pack_id="alpha",
                        risk_tier="read",
                    )
                )
                prev_hash = entry_hash
            await session.commit()

        # 1. Valid multi-page verification across identical-ts boundary (evt-004 -> evt-005)
        async with session_factory() as ok_session:
            ok_res = await verify_profile_audit_chain(ok_session, profile_id, batch_size=5)
        assert ok_res["valid"] is True
        assert ok_res["checked_count"] == 18

        # 2. Break prev_hash on evt-005 (first record of page 2, straddling page 1 -> page 2)
        async with session_factory() as tamper_session:
            orig_prev = (
                await tamper_session.execute(
                    text("SELECT prev_hash FROM audit_events WHERE id = 'evt-005'")
                )
            ).scalar_one()
            await tamper_session.execute(
                text("UPDATE audit_events SET prev_hash = :bad WHERE id = 'evt-005'"),
                {"bad": "f" * 64},
            )
            await tamper_session.commit()

        async with session_factory() as check_p2_session:
            with count_sql_statements(engine) as p2_counter:
                broken_p2 = await verify_profile_audit_chain(
                    check_p2_session, profile_id, batch_size=5
                )
        assert broken_p2["valid"] is False
        assert broken_p2["reason"] == "prev_hash_mismatch"
        assert broken_p2["broken_at_event_id"] == "evt-005"
        assert broken_p2["checked_count"] == 6
        # Early exit on page 2 without fetching pages 3 or 4
        assert len(p2_counter.selects) == 2

        # 3. Restore evt-005 and tamper payload_hash on evt-010 (first record of page 3)
        async with session_factory() as restore_session:
            await restore_session.execute(
                text("UPDATE audit_events SET prev_hash = :orig WHERE id = 'evt-005'"),
                {"orig": orig_prev},
            )
            await restore_session.execute(
                text("UPDATE audit_events SET payload_hash = :bad WHERE id = 'evt-010'"),
                {"bad": "9" * 64},
            )
            await restore_session.commit()

        async with session_factory() as check_p3_session:
            with count_sql_statements(engine) as p3_counter:
                broken_p3 = await verify_profile_audit_chain(
                    check_p3_session, profile_id, batch_size=5
                )
        assert broken_p3["valid"] is False
        assert broken_p3["reason"] == "hash_mismatch"
        assert broken_p3["broken_at_event_id"] == "evt-010"
        assert broken_p3["checked_count"] == 11
        assert len(p3_counter.selects) == 3


@pytest.mark.asyncio
async def test_orch_eval_async_helpers_avoid_blocking_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """orch_eval judge and ollama_backend avoid time.sleep and urllib.request.urlopen."""
    judge_ast = ast.parse(Path(orch_judge.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(judge_ast):
        if isinstance(node, ast.Attribute) and node.attr == "sleep":
            assert not (isinstance(node.value, ast.Name) and node.value.id == "time")

    ollama_ast = ast.parse(Path(ollama_backend.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(ollama_ast):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("urllib") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("urllib")

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "healthy.local":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "glm-4.7-flash:latest", "digest": "sha256:111"},
                        {"name": "llama3.1:8b", "digest": "sha256:222"},
                    ]
                },
            )
        return httpx.Response(503, text="service unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler)) as mock_client:
        ok_status = await ollama_backend.aprobe_ollama(
            "http://healthy.local:11434",
            client=mock_client,
        )
        down_status = await ollama_backend.aprobe_ollama(
            "http://down.local:11434",
            client=mock_client,
        )

    assert ok_status.reachable is True
    assert ok_status.has("glm-4.7-flash")
    assert ok_status.digests["llama3.1:8b"] == "sha256:222"
    assert down_status.reachable is False
    assert down_status.error is not None

    # Verify sync probe_ollama works safely even when invoked from inside a running event loop
    async def _fake_aprobe(base_url: str = "", timeout_s: float = 2.0, *, client: Any = None):
        await orch_judge.asyncio.sleep(0.001)
        return ollama_backend.OllamaStatus(
            reachable=True,
            base_url=base_url,
            models=["llama3.1:8b"],
        )

    monkeypatch.setattr(ollama_backend, "aprobe_ollama", _fake_aprobe)
    bridged = ollama_backend.probe_ollama("http://127.0.0.1:11434")
    assert bridged.reachable is True
    assert bridged.has("llama3.1:8b")

    # Verify async judge retry + aggregation
    class _AsyncRetryJudge:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, _messages: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="malformed non-json output")
            return AIMessage(
                content=json.dumps(
                    {
                        "score": 5,
                        "verdict": "pass",
                        "reasons": ["recovered on async retry"],
                        "evidence_quotes": ["$420"],
                    }
                )
            )

    judge_model = _AsyncRetryJudge()
    verdict = await orch_judge.ascore_once(
        judge_model,
        rubric_md="Score 1-5.",
        criteria="accurate total",
        user="What is the balance?",
        answer="Balance is $420.",
        trace_summary={"agents": ["budget-planner"]},
        retry_delay_s=0.001,
    )
    assert verdict.parse_ok is True
    assert verdict.score == 5
    assert judge_model.calls == 2

    agg = await orch_judge.ascore_turn(
        judge_model,
        rubric="synthesis",
        criteria="accurate total",
        user="What is the balance?",
        answer="Balance is $420.",
        trace_summary={"agents": ["budget-planner"]},
        samples=2,
        retry_delay_s=0.001,
    )
    assert agg.verdict == "pass"
    assert agg.score == 5
    assert len(agg.samples) == 2


def test_testing_package_reexports_shared_factories() -> None:
    """yarvelle_core.testing lazily exposes shared DB, client, query-counter, and entity factories."""
    assert callable(create_test_session_factory)
    assert callable(create_auth_client)
    assert callable(count_sql_statements)
    assert callable(async_db_engine_and_factory)
    assert callable(async_db_session)
    assert callable(auth_client)
    assert SQLStatementCounter is not None
    principal = UserFactory.build_principal(username="steward_check")
    assert principal.username == "steward_check"
    profile = ProfileFactory.build(user_id=principal.id, name="Check")
    conn = ConnectionFactory.build(user_id=principal.id, profile_id=profile.id)
    assert conn.profile_id == profile.id
