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

"""Stored hand-off records (``turn_tasks``) and fail-loud audit writes.

Covers the ``turn_tasks`` table and its migration, the new audit columns,
and ``record_audit`` durability: a failed write of a strict event raises,
a best-effort failure is logged and counted. Everything runs on local SQLite.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, List

import pytest
import sqlalchemy as sa
from alembic import command
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

import yarvelle_core.audit.logger as audit_logger
from tests.test_hybrid_routing import ScriptedModel, Sink, _spec, _task_call, _turn, _write_agent
from yarvelle_core.agents import AgentRegistry
from yarvelle_core.audit import AuditWriteError, best_effort_failure_count, record_audit
from yarvelle_core.db.models import AuditEventRecord, TurnTask
from yarvelle_core.db.schema_catalog import SYSTEM_DENYLIST_TABLES
from yarvelle_core.db.session import get_alembic_config
from yarvelle_core.engine.orchestration import HybridRouter
from yarvelle_core.engine.orchestration.runtime import build_turn_tasks, store_turn_tasks
from yarvelle_core.engine.orchestration.task_guard import OrchestrationAuditError
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import TurnTaskRecord
from yarvelle_core.testing.fixtures import create_test_session_factory

H1 = hashlib.sha256(b"in").hexdigest()
H2 = hashlib.sha256(b"out").hexdigest()


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    for agent_id in ("budget-planner", "trip-organizer", "doc-reader"):
        _write_agent(agents, agent_id)
    _write_agent(agents, "secret-helper", hidden=True)
    return AgentRegistry(agents_dir=agents)


@pytest.fixture()
async def factory() -> Any:
    async with create_test_session_factory(session_class=AsyncSession) as (_engine, session_factory):
        yield session_factory


def _broken_factory() -> Any:
    raise OSError("database is down")


# ------------------------------------------------------------------ turn task records


def test_build_turn_tasks_one_row_per_hand_off_in_order() -> None:
    records = [
        AuditEvent(event="task.started", agent_id="trip-organizer", task_id="t1", turn_id="turn-1",
                   input_hash=H1, ts="2026-11-04T10:00:00+00:00"),
        AuditEvent(event="task.failed", agent_id="secret-helper", task_id="t2", turn_id="turn-1",
                   error_code="agent.hidden"),
        AuditEvent(event="task.completed", agent_id="trip-organizer", task_id="t1", turn_id="turn-1",
                   output_hash=H2, duration_ms=12.6),
        AuditEvent(event="route.main_agent", agent_id="main-agent", turn_id="turn-1"),
    ]
    rows = build_turn_tasks(records, [], {"trip-organizer": "Trip Organizer"}, turn_id="turn-1", thread_id="th")
    assert [(r.task_id, r.agent_id, r.state) for r in rows] == [
        ("t1", "trip-organizer", "completed"),
        ("t2", "secret-helper", "failed"),
    ]
    first, refused = rows
    assert first.agent_title == "Trip Organizer" and first.thread_id == "th"
    assert first.input_hash == H1 and first.output_hash == H2
    assert first.started_at == "2026-11-04T10:00:00+00:00" and first.duration_ms == 13
    assert refused.started_at is None and refused.error_code == "agent.hidden"
    assert refused.agent_title == "secret-helper"


def test_turn_task_record_rejects_bad_hashes() -> None:
    with pytest.raises(ValueError):
        TurnTaskRecord(turn_id="t", task_id="x", agent_id="a", agent_title="A", state="completed", input_hash="nope")


def test_main_agent_turn_stores_its_hand_offs(registry: AgentRegistry) -> None:
    stored: List[TurnTaskRecord] = []
    model = ScriptedModel(
        script=[_task_call("trip-organizer", "call-1"), AIMessage(content="Day 1: beach."), AIMessage(content="Plan: beach.")]
    )
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=Sink(), task_sink=stored.extend)
    asyncio.run(router.run(_turn("plan a weekend"), turn_id="turn-9", thread_id="th-9"))
    assert [(r.turn_id, r.task_id, r.agent_id, r.state) for r in stored] == [
        ("turn-9", "call-1", "trip-organizer", "completed")
    ]
    assert stored[0].agent_title == "Trip Organizer" and stored[0].thread_id == "th-9"
    assert stored[0].verified is True and stored[0].duration_ms is not None


def test_failed_turn_task_write_stops_the_turn() -> None:
    def broken(rows: Any) -> None:
        raise OSError("disk full")

    row = TurnTaskRecord(turn_id="t", task_id="x", agent_id="a", agent_title="A", state="completed")
    with pytest.raises(OrchestrationAuditError):
        asyncio.run(store_turn_tasks(broken, [row]))
    asyncio.run(store_turn_tasks(None, [row]))  # no sink: nothing to do


async def test_default_sink_writes_turn_task_rows(factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import yarvelle_core.db.session as db_session
    from yarvelle_core.engine.builder import _store_turn_tasks

    monkeypatch.setattr(db_session, "get_session_factory", lambda *a, **k: factory)
    row = TurnTaskRecord(
        turn_id="turn-1", task_id="call-1", thread_id="th", agent_id="trip-organizer", agent_title="Trip Organizer",
        state="completed", input_hash=H1, output_hash=H2, started_at="2026-11-04T10:00:00+00:00", duration_ms=40,
    )
    await _store_turn_tasks([row])

    async with factory() as session:
        (saved,) = list((await session.execute(sa.select(TurnTask))).scalars())
    assert (saved.turn_id, saved.task_id, saved.agent_id, saved.state) == ("turn-1", "call-1", "trip-organizer", "completed")
    assert saved.output_hash == H2 and saved.duration_ms == 40 and saved.started_at is not None
    assert saved.scope
    assert "turn_tasks" in SYSTEM_DENYLIST_TABLES


# ------------------------------------------------------------------ fail-loud audit


def test_strict_audit_write_failure_raises(tmp_path: Path) -> None:
    event = AuditEvent(event="route.fixed", agent_id="doc-reader", turn_id="turn-1")
    with pytest.raises(AuditWriteError):
        asyncio.run(record_audit(event, log_path=tmp_path / "a.jsonl", session_factory=_broken_factory))


async def test_strict_audit_file_failure_raises(tmp_path: Path, factory: Any) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()  # a directory, so the JSONL append fails
    event = AuditEvent(event="task.started", agent_id="trip-organizer", task_id="t1")
    with pytest.raises(AuditWriteError):
        await record_audit(event, log_path=blocked, session_factory=factory)


def test_best_effort_failure_is_counted_not_raised(tmp_path: Path) -> None:
    before = best_effort_failure_count()
    event = AuditEvent(event="tool", agent_id="trip-organizer", tool="lookup")
    asyncio.run(record_audit(event, log_path=tmp_path / "a.jsonl", session_factory=_broken_factory))
    assert best_effort_failure_count() == before + 1
    assert (tmp_path / "a.jsonl").is_file()


def test_mode_overrides_event_durability(tmp_path: Path) -> None:
    event = AuditEvent(event="tool", agent_id="trip-organizer")
    with pytest.raises(AuditWriteError):
        asyncio.run(record_audit(event, log_path=tmp_path / "a.jsonl", session_factory=_broken_factory, mode="strict"))
    assert audit_logger.AuditWriteError is AuditWriteError


async def test_audit_record_keeps_turn_and_task_fields(tmp_path: Path, factory: Any) -> None:
    event = AuditEvent(
        event="task.completed", agent_id="trip-organizer", turn_id="turn-1", task_id="call-1",
        parent_task_id="call-0", input_hash=H1, output_hash=H2, error_code="none",
    )
    await record_audit(event, log_path=tmp_path / "a.jsonl", session_factory=factory)

    async with factory() as session:
        saved = (await session.execute(sa.select(AuditEventRecord))).scalars().one()
    assert (saved.turn_id, saved.task_id, saved.parent_task_id) == ("turn-1", "call-1", "call-0")
    assert (saved.input_hash, saved.output_hash, saved.error_code) == (H1, H2, "none")


# ------------------------------------------------------------------ migration


def test_migration_adds_turn_tasks_and_audit_columns(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    new_cols = {"turn_id", "task_id", "parent_task_id", "input_hash", "output_hash", "error_code"}
    with engine.begin() as conn:
        cfg = get_alembic_config(conn)
        command.upgrade(cfg, "0012_agent_extensions")
        assert "turn_tasks" not in sa.inspect(conn).get_table_names()
        command.upgrade(cfg, "0013_turn_tasks")
        insp = sa.inspect(conn)
        assert "turn_tasks" in insp.get_table_names()
        assert new_cols <= {c["name"] for c in insp.get_columns("audit_events")}
        task_cols = {c["name"] for c in insp.get_columns("turn_tasks")}
        assert {"turn_id", "task_id", "agent_id", "state", "output_hash", "duration_ms", "scope"} <= task_cols
        uniques = [tuple(u["column_names"]) for u in insp.get_unique_constraints("turn_tasks")]
        assert ("turn_id", "task_id") in uniques
        conn.execute(sa.text(
            "INSERT INTO turn_tasks (id, turn_id, task_id, agent_id, agent_title, state, created_at)"
            " VALUES ('r1', 'turn-1', 'call-1', 'a', 'A', 'completed', '2026-11-04 10:00:00')"
        ))
        row = conn.execute(sa.text("SELECT scope, truncated, verified FROM turn_tasks")).one()
        assert row.scope and not row.truncated and not row.verified

        command.downgrade(cfg, "0012_agent_extensions")
        insp = sa.inspect(conn)
        assert "turn_tasks" not in insp.get_table_names()
        assert not new_cols & {c["name"] for c in insp.get_columns("audit_events")}
    engine.dispose()
