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

"""Checkpoint encryption at rest: serializer, savers, resume, and migration.

Keys are random bytes generated per test; nothing here touches a real keyring.
"""

from __future__ import annotations

import asyncio
import json
import operator
import os
from pathlib import Path
import sqlite3
from typing import Annotated, List, TypedDict
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
import pytest

from yarvelle_core import cli, identity
from yarvelle_core.config import settings
from yarvelle_core.engine.graph import (
    EncryptedAsyncSqliteSaver,
    EncryptedSqliteSaver,
    create_async_sqlite_saver,
    create_sqlite_saver,
)
from yarvelle_core.vault import checkpoints as cp
from yarvelle_core.vault.errors import VaultLockedError


@pytest.fixture(autouse=True)
def _clean_keyring_cache(monkeypatch: pytest.MonkeyPatch):
    cp.reset_checkpoint_keyring_cache()
    monkeypatch.setattr(settings, "checkpoint_encryption", False)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", True)
    monkeypatch.setattr(settings, "checkpoint_key_version", 1)
    yield
    cp.reset_checkpoint_keyring_cache()


@pytest.fixture()
def kek() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def vault_kek(monkeypatch: pytest.MonkeyPatch, kek: bytes) -> bytes:
    """Serve ``kek`` as the vault KEK without touching any OS keyring."""
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: kek)
    return kek


def marker() -> str:
    return f"PLAINTEXT-MARKER-{uuid.uuid4().hex}"


def raw_db_bytes(db: Path) -> bytes:
    data = b""
    for suffix in ("", "-wal"):
        p = Path(str(db) + suffix)
        if p.exists():
            data += p.read_bytes()
    return data


def column_types(db: Path) -> List[str]:
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute("SELECT type FROM checkpoints").fetchall()
        rows += conn.execute("SELECT type FROM writes").fetchall()
    return [r[0] for r in rows if r[0] is not None]


class State(TypedDict):
    notes: Annotated[List[str], operator.add]


def build_graph(checkpointer, note: str):
    """write -> approve (interrupts for a human answer) -> end."""

    def write(state: State):
        return {"notes": [note]}

    def approve(state: State):
        answer = interrupt({"question": f"approve {note}?"})
        return {"notes": [f"approved:{answer}"]}

    g = StateGraph(State)
    g.add_node("write", write)
    g.add_node("approve", approve)
    g.add_edge(START, "write")
    g.add_edge("write", "approve")
    g.add_edge("approve", END)
    return g.compile(checkpointer=checkpointer)


def build_echo_graph(checkpointer):
    def echo(state: State):
        return {"notes": [f"seen:{len(state['notes'])}"]}

    g = StateGraph(State)
    g.add_node("echo", echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile(checkpointer=checkpointer)


def cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


# ---------------------------------------------------------------------------
# Keys and envelope
# ---------------------------------------------------------------------------


def test_key_derivation_is_deterministic_versioned_and_hidden(kek: bytes):
    k1 = cp.derive_checkpoint_key(kek, 1)
    assert k1 == cp.derive_checkpoint_key(kek, 1)
    k2 = cp.derive_checkpoint_key(kek, 2)
    assert k1.key != k2.key and len(k1.key) == 32
    assert k1.key != kek
    assert k1.key_id.startswith("v1-") and k2.key_id.startswith("v2-")
    assert k1.key.hex() not in repr(k1)
    ring = cp.CheckpointKeyring.from_kek(kek, 2)
    assert ring.active.key_id == k2.key_id
    assert ring.get(k1.key_id) is not None
    assert k1.key.hex() not in repr(ring) and k2.key.hex() not in repr(ring)


def test_key_derivation_follows_configured_vault_salt(kek: bytes, monkeypatch: pytest.MonkeyPatch):
    default = cp.derive_checkpoint_key(kek)
    monkeypatch.setenv(identity.env_name("VAULT_SALT"), "another_16b_salt")
    assert cp.derive_checkpoint_key(kek).key != default.key


def test_bad_kek_and_version_rejected():
    with pytest.raises(cp.CheckpointKeyError):
        cp.derive_checkpoint_key(b"short")
    with pytest.raises(cp.CheckpointKeyError):
        cp.derive_checkpoint_key(os.urandom(32), 0)


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def test_round_trip_and_ciphertext_hides_plaintext(kek: bytes):
    serde = cp.EncryptedCheckpointSerializer(cp.CheckpointKeyring.from_kek(kek))
    secret = marker()
    value = {"messages": [secret], "n": 3, "blob": secret.encode()}
    typ, blob = serde.dumps_typed(value)
    assert typ.endswith("+aes256gcm")
    assert secret.encode() not in blob
    assert serde.loads_typed((typ, blob)) == value


def test_wrong_key_fails_clearly(kek: bytes):
    typ, blob = cp.EncryptedCheckpointSerializer(cp.CheckpointKeyring.from_kek(kek)).dumps_typed({"a": 1})
    other = cp.EncryptedCheckpointSerializer(cp.CheckpointKeyring.from_kek(os.urandom(32)))
    with pytest.raises(cp.CheckpointKeyError, match="not loaded"):
        other.loads_typed((typ, blob))


def test_tampered_blob_and_swapped_key_id_fail(kek: bytes):
    ring = cp.CheckpointKeyring.from_kek(kek, 2)
    serde = cp.EncryptedCheckpointSerializer(ring)
    typ, blob = serde.dumps_typed({"a": "b"})
    flipped = bytearray(blob)
    flipped[-1] ^= 0x01
    with pytest.raises(cp.CheckpointDecryptionError):
        serde.loads_typed((typ, bytes(flipped)))
    # Relabel a v2 envelope as the (loaded) v1 key: the header is authenticated.
    v1 = cp.derive_checkpoint_key(kek, 1).key_id.encode()
    v2 = ring.active.key_id.encode()
    assert len(v1) == len(v2)
    with pytest.raises(cp.CheckpointDecryptionError):
        serde.loads_typed((typ, blob.replace(v2, v1, 1)))
    with pytest.raises(cp.CheckpointDecryptionError):
        serde.loads_typed((typ, blob[:20]))
    with pytest.raises(cp.CheckpointDecryptionError):
        serde.loads_typed(("msgpack+rot13", blob))


def test_plaintext_reads_allowed_then_refused(kek: bytes):
    legacy = JsonPlusSerializer().dumps_typed({"old": True})
    ring = cp.CheckpointKeyring.from_kek(kek)
    assert cp.EncryptedCheckpointSerializer(ring).loads_typed(legacy) == {"old": True}
    strict = cp.EncryptedCheckpointSerializer(ring, allow_plaintext_reads=False)
    with pytest.raises(cp.PlaintextCheckpointError, match="checkpoints encrypt"):
        strict.loads_typed(legacy)


def test_plaintext_serializer_names_encrypted_rows(kek: bytes):
    enc = cp.EncryptedCheckpointSerializer(cp.CheckpointKeyring.from_kek(kek)).dumps_typed({"a": 1})
    with pytest.raises(cp.CheckpointKeyError, match="encryption is turned off"):
        cp.PlaintextCheckpointSerializer().loads_typed(enc)
    plain = JsonPlusSerializer().dumps_typed({"a": 1})
    assert cp.PlaintextCheckpointSerializer().loads_typed(plain) == {"a": 1}


def test_allowlist_narrowing_keeps_encrypted_serializer(kek: bytes, tmp_path: Path):
    strict_inner = JsonPlusSerializer(allowed_msgpack_modules=None)
    serde = cp.EncryptedCheckpointSerializer(
        cp.CheckpointKeyring.from_kek(kek), strict_inner, allow_plaintext_reads=False
    )
    saver = create_sqlite_saver(tmp_path / "a.db", serde=serde)
    try:
        assert isinstance(saver, EncryptedSqliteSaver)
        narrowed = saver.with_allowlist([("tests", "Thing")])
        assert narrowed is not saver
        assert isinstance(narrowed.serde, cp.EncryptedCheckpointSerializer)
        assert narrowed.serde.allow_plaintext_reads is False
        assert narrowed.serde.serde is not strict_inner
    finally:
        saver.conn.close()


# ---------------------------------------------------------------------------
# Settings wiring
# ---------------------------------------------------------------------------


def test_savers_follow_settings(vault_kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    off = create_sqlite_saver(tmp_path / "off.db")
    assert isinstance(off.serde, cp.PlaintextCheckpointSerializer)
    off.conn.close()

    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    on = create_sqlite_saver(tmp_path / "on.db")
    try:
        assert isinstance(on, EncryptedSqliteSaver)
        assert isinstance(on.serde, cp.EncryptedCheckpointSerializer)
        assert on.serde.allow_plaintext_reads is False
        assert on.serde.keyring.active.key_id == cp.derive_checkpoint_key(vault_kek).key_id
    finally:
        on.conn.close()


def test_missing_vault_key_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def locked() -> bytes:
        raise VaultLockedError("no key")

    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", locked)
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    with pytest.raises(cp.CheckpointKeyError, match="vault key"):
        create_sqlite_saver(tmp_path / "x.db")

    async def open_async():
        async with create_async_sqlite_saver(tmp_path / "y.db"):
            pass

    with pytest.raises(cp.CheckpointKeyError):
        asyncio.run(open_async())


def test_vault_key_from_secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key_file = tmp_path / "kek"
    key_file.write_text(os.urandom(32).hex())
    monkeypatch.setenv(identity.env_name("MODE"), "server")
    monkeypatch.setenv(identity.env_name("VAULT_KEK_FILE"), str(key_file))
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    serde = cp.checkpoint_serializer()
    assert isinstance(serde, cp.EncryptedCheckpointSerializer)
    assert cp.load_checkpoint_keyring() is serde.keyring  # cached per process


# ---------------------------------------------------------------------------
# Graph resume through encrypted checkpoints
# ---------------------------------------------------------------------------


def test_encrypted_thread_resumes_after_interrupt(vault_kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    db = tmp_path / "resume.db"
    secret = marker()

    async def first_turn():
        async with create_async_sqlite_saver(db) as saver:
            assert isinstance(saver, EncryptedAsyncSqliteSaver)
            graph = build_graph(saver, secret)
            out = await graph.ainvoke({"notes": []}, cfg("t1"))
            assert "__interrupt__" in out
            state = await graph.aget_state(cfg("t1"))
            assert state.next == ("approve",)

    async def resume():
        async with create_async_sqlite_saver(db) as saver:
            graph = build_graph(saver, secret)
            return await graph.ainvoke(Command(resume="yes"), cfg("t1"))

    asyncio.run(first_turn())
    raw = raw_db_bytes(db)
    assert secret.encode() not in raw
    assert b"approve " not in raw  # interrupt payload is sealed too
    assert all(t.endswith("+aes256gcm") for t in column_types(db))

    cp.reset_checkpoint_keyring_cache()  # fresh process: key re-derived from the vault
    result = asyncio.run(resume())
    assert result["notes"] == [secret, "approved:yes"]
    assert secret.encode() not in raw_db_bytes(db)


def test_resume_with_wrong_vault_key_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kek: bytes):
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: kek)
    db = tmp_path / "wrong.db"
    saver = create_sqlite_saver(db)
    build_graph(saver, marker()).invoke({"notes": []}, cfg("t"))
    saver.conn.close()

    cp.reset_checkpoint_keyring_cache()
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: os.urandom(32))
    saver = create_sqlite_saver(db)
    try:
        with pytest.raises(cp.CheckpointKeyError, match="not loaded"):
            build_graph(saver, "x").invoke(Command(resume="yes"), cfg("t"))
    finally:
        saver.conn.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def _legacy_db(tmp_path: Path, secret: str) -> Path:
    """A checkpoint DB written with encryption off (plaintext rows), paused at an interrupt."""
    db = tmp_path / "legacy.db"
    saver = create_sqlite_saver(db)
    assert isinstance(saver.serde, cp.PlaintextCheckpointSerializer)
    build_graph(saver, secret).invoke({"notes": []}, cfg("old"))
    saver.conn.close()
    assert secret.encode() in raw_db_bytes(db)
    return db


def test_mixed_plaintext_and_encrypted_reads_during_migration(
    vault_kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = marker()
    db = _legacy_db(tmp_path, secret)
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    saver = create_sqlite_saver(db)
    try:
        # Legacy thread resumes from plaintext rows; new rows are written encrypted.
        result = build_graph(saver, secret).invoke(Command(resume="ok"), cfg("old"))
        assert result["notes"] == [secret, "approved:ok"]
        build_echo_graph(saver).invoke({"notes": ["new"]}, cfg("new"))
        types = column_types(db)
        assert any(t.endswith("+aes256gcm") for t in types)
        assert any("+" not in t for t in types)
        history = list(saver.list(cfg("old")))
        assert history and history[0].checkpoint["channel_values"]["notes"][-1] == "approved:ok"
    finally:
        saver.conn.close()


def test_migration_encrypts_is_idempotent_and_reversible(
    vault_kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = marker()
    db = _legacy_db(tmp_path, secret)
    ring = cp.CheckpointKeyring.from_kek(vault_kek)

    before = cp.checkpoint_db_status(db, ring)
    assert before.plaintext_rows > 0 and before.encrypted_rows == 0

    dry = cp.encrypt_checkpoint_db(db, ring, dry_run=True)
    assert dry.rows_changed == before.plaintext_rows and dry.backup_path is None
    assert cp.checkpoint_db_status(db, ring).plaintext_rows == before.plaintext_rows

    done = cp.encrypt_checkpoint_db(db, ring)
    assert done.rows_changed == before.plaintext_rows
    backup = Path(done.backup_path)
    assert backup.exists() and secret.encode() in backup.read_bytes()
    after = cp.checkpoint_db_status(db, ring)
    assert after.plaintext_rows == 0 and after.active_key_rows == before.plaintext_rows
    assert secret.encode() not in raw_db_bytes(db)

    again = cp.encrypt_checkpoint_db(db, ring)
    assert again.rows_changed == 0 and again.backup_path is None

    # With plaintext reads off, the migrated thread still resumes.
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    saver = create_sqlite_saver(db)
    try:
        result = build_graph(saver, secret).invoke(Command(resume="ok"), cfg("old"))
        assert result["notes"] == [secret, "approved:ok"]
    finally:
        saver.conn.close()

    # Reverse path back to plaintext, readable with encryption off.
    undone = cp.decrypt_checkpoint_db(db, ring)
    assert undone.rows_changed > 0
    assert cp.checkpoint_db_status(db, ring).encrypted_rows == 0
    assert cp.decrypt_checkpoint_db(db, ring).rows_changed == 0
    monkeypatch.setattr(settings, "checkpoint_encryption", False)
    saver = create_sqlite_saver(db)
    try:
        state = build_graph(saver, secret).get_state(cfg("old"))
        assert state.values["notes"] == [secret, "approved:ok"]
    finally:
        saver.conn.close()


def test_strict_reads_refuse_unmigrated_rows(vault_kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = _legacy_db(tmp_path, marker())
    monkeypatch.setattr(settings, "checkpoint_encryption", True)
    monkeypatch.setattr(settings, "checkpoint_plaintext_reads", False)
    saver = create_sqlite_saver(db)
    try:
        with pytest.raises(cp.PlaintextCheckpointError):
            build_graph(saver, "x").get_state(cfg("old"))
    finally:
        saver.conn.close()


def test_key_rotation_reencrypts_to_active_version(kek: bytes, tmp_path: Path):
    db = tmp_path / "rot.db"
    v1 = cp.CheckpointKeyring.from_kek(kek, 1)
    saver = create_sqlite_saver(db, serde=cp.EncryptedCheckpointSerializer(v1))
    secret = marker()
    build_graph(saver, secret).invoke({"notes": []}, cfg("r"))
    saver.conn.close()

    v2 = cp.CheckpointKeyring.from_kek(kek, 2)
    status = cp.checkpoint_db_status(db, v2)
    assert status.active_key_rows == 0 and status.other_key_rows == {v1.active.key_id: status.encrypted_rows}

    # Old rows stay readable under v2 before migration.
    saver = create_sqlite_saver(db, serde=cp.EncryptedCheckpointSerializer(v2))
    assert build_graph(saver, secret).get_state(cfg("r")).values["notes"] == [secret]
    saver.conn.close()

    report = cp.encrypt_checkpoint_db(db, v2, backup=False)
    assert report.rows_changed == status.encrypted_rows
    after = cp.checkpoint_db_status(db, v2)
    assert after.other_key_rows == {} and after.active_key_rows == status.encrypted_rows


def test_migration_with_wrong_key_changes_nothing(kek: bytes, tmp_path: Path):
    db = tmp_path / "wk.db"
    ring = cp.CheckpointKeyring.from_kek(kek)
    saver = create_sqlite_saver(db, serde=cp.EncryptedCheckpointSerializer(ring))
    build_graph(saver, marker()).invoke({"notes": []}, cfg("w"))
    saver.conn.close()
    original = raw_db_bytes(db)

    wrong = cp.CheckpointKeyring.from_kek(os.urandom(32))
    with pytest.raises(cp.CheckpointKeyError):
        cp.decrypt_checkpoint_db(db, wrong, backup=False)
    with pytest.raises(cp.CheckpointKeyError):
        cp.encrypt_checkpoint_db(db, wrong, backup=False)
    assert cp.checkpoint_db_status(db, ring).active_key_rows > 0
    assert raw_db_bytes(db) == original


def test_cli_status_dry_run_and_encrypt(vault_kek: bytes, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    secret = marker()
    db = _legacy_db(tmp_path, secret)

    assert cli.main(["checkpoints", "status", "--db", str(db), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["plaintext_rows"] > 0

    assert cli.main(["checkpoints", "encrypt", "--db", str(db), "--dry-run", "--json"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] is True and dry["rows_changed"] == status["plaintext_rows"]
    assert secret.encode() in raw_db_bytes(db)

    assert cli.main(["checkpoints", "encrypt", "--db", str(db), "--no-backup"]) == 0
    out = capsys.readouterr().out
    assert "Plaintext reads can be turned off" in out
    assert vault_kek.hex() not in out
    assert secret.encode() not in raw_db_bytes(db)
    assert not list(tmp_path.glob("legacy.db.bak-*"))

    assert cli.main(["checkpoints", "status", "--db", str(tmp_path / "missing.db")]) == 1


def test_cli_reports_locked_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def locked() -> bytes:
        raise VaultLockedError("no key")

    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", locked)
    assert cli.main(["checkpoints", "status", "--db", str(tmp_path / "x.db")]) == 1
    assert "vault key" in capsys.readouterr().err


def test_memory_saver_with_encrypted_serde_round_trips(kek: bytes):
    saver = MemorySaver(serde=cp.EncryptedCheckpointSerializer(cp.CheckpointKeyring.from_kek(kek)))
    secret = marker()
    graph = build_graph(saver, secret)
    graph.invoke({"notes": []}, cfg("m"))
    assert graph.invoke(Command(resume="y"), cfg("m"))["notes"] == [secret, "approved:y"]
