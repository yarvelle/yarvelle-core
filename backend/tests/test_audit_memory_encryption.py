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

"""Opt-in audit/memory at-rest encryption: envelopes, AAD, and scoped search."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yarvelle_core.config import settings
from yarvelle_core.memory.adapters.sqlite.memory_adapter import SqliteMemoryAdapter
from yarvelle_core.memory.ports.memory_port import MemoryTier
from yarvelle_core.vault import field_crypto as fc
from yarvelle_core.vault.field_crypto import (
    FieldDecryptionError,
    FieldKeyring,
    PlaintextFieldError,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    fc.reset_field_keyring_cache()
    monkeypatch.setattr(settings, "audit_encryption", False)
    monkeypatch.setattr(settings, "audit_plaintext_reads", True)
    monkeypatch.setattr(settings, "memory_encryption", False)
    monkeypatch.setattr(settings, "memory_plaintext_reads", True)
    monkeypatch.setattr(settings, "audit_key_version", 1)
    monkeypatch.setattr(settings, "memory_key_version", 1)
    yield
    fc.reset_field_keyring_cache()


@pytest.fixture()
def kek() -> bytes:
    return os.urandom(32)


def test_seal_roundtrip_and_aad(kek: bytes) -> None:
    ring = FieldKeyring.from_kek(kek, fc.PURPOSE_AUDIT, 1)
    aad = fc.build_aad(["audit", "profile-1", "tool", "evt-1", "run-1"])
    sealed = fc.seal_text(ring, '{"prompt":"SECRET-BODY"}', aad)
    assert sealed.startswith(fc.TEXT_PREFIX)
    assert "SECRET-BODY" not in sealed
    opened = fc.open_text(ring, sealed, aad, allow_plaintext=False)
    assert opened == '{"prompt":"SECRET-BODY"}'
    with pytest.raises(FieldDecryptionError):
        fc.open_text(
            ring,
            sealed,
            fc.build_aad(["audit", "profile-2", "tool", "evt-1", "run-1"]),
            allow_plaintext=False,
        )


def test_wrong_key_fails(kek: bytes) -> None:
    ring = FieldKeyring.from_kek(kek, fc.PURPOSE_MEMORY, 1)
    other = FieldKeyring.from_kek(os.urandom(32), fc.PURPOSE_MEMORY, 1)
    aad = fc.build_aad(["memory", "ns", "k", "semantic", "id"])
    sealed = fc.seal_text(ring, "plain", aad)
    with pytest.raises(Exception):
        fc.open_text(other, sealed, aad, allow_plaintext=False)


def test_plaintext_reads_policy(kek: bytes) -> None:
    ring = FieldKeyring.from_kek(kek, fc.PURPOSE_AUDIT, 1)
    aad = fc.build_aad(["audit", None, "run", "1", None])
    assert fc.open_text(ring, "legacy-plain", aad, allow_plaintext=True) == "legacy-plain"
    with pytest.raises(PlaintextFieldError):
        fc.open_text(ring, "legacy-plain", aad, allow_plaintext=False)


@pytest.mark.asyncio
async def test_memory_encryption_zero_plaintext_and_scoped_search(
    kek: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "memory_encryption", True)
    monkeypatch.setattr(settings, "memory_plaintext_reads", False)
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: kek)
    fc.reset_field_keyring_cache()

    db = tmp_path / "mem.db"
    adapter = SqliteMemoryAdapter(db_path=db)
    secret = f"SECRET-MEMORY-{os.urandom(4).hex()}"
    await adapter.remember("note-1", secret, MemoryTier.SEMANTIC, namespace="profile:demo:notes")
    raw = b""
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db) + suffix)
        if path.exists():
            raw += path.read_bytes()
    assert secret.encode() not in raw
    assert b"enc:v1:" in raw

    hits = await adapter.recall("SECRET-MEMORY", namespace="profile:demo:notes", limit=5)
    assert hits
    assert secret in str(hits[0]["value"])
    if adapter._conn is not None:
        await adapter._conn.commit()
        await adapter._conn.close()
        adapter._conn = None

    # Re-open adapter (new connection) and confirm ciphertext still decrypts.
    adapter2 = SqliteMemoryAdapter(db_path=db)
    hits2 = await adapter2.recall("SECRET-MEMORY", namespace="profile:demo:notes", limit=5)
    assert hits2 and secret in str(hits2[0]["value"])


@pytest.mark.asyncio
async def test_audit_logger_seals_detail(
    kek: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "audit_encryption", True)
    monkeypatch.setattr(settings, "audit_plaintext_reads", False)
    monkeypatch.setattr(settings, "audit_store_bodies", True)
    monkeypatch.setattr("yarvelle_core.vault.kek.get_kek", lambda: kek)
    fc.reset_field_keyring_cache()

    from yarvelle_core.audit.logger import _maybe_seal_audit_detail, open_audit_detail

    body = '{"prompt":"AUDIT-SECRET","agent_id":"assistant"}'
    sealed = _maybe_seal_audit_detail(
        body,
        record_id="evt-1",
        profile_id="prof-1",
        event_type="tool",
        run_id="run-1",
    )
    assert sealed is not None
    assert sealed.startswith("enc:v1:")
    assert "AUDIT-SECRET" not in sealed
    opened = open_audit_detail(
        sealed,
        record_id="evt-1",
        profile_id="prof-1",
        event_type="tool",
        run_id="run-1",
    )
    assert opened == body
