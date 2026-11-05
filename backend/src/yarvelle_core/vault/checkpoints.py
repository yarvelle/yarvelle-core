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

"""Encryption at rest for LangGraph checkpoints.

Checkpoint blobs (conversation state, tool results, pending writes) are sealed
with AES-256-GCM before they reach the checkpoint database. The key is derived
from the vault KEK with HKDF-SHA256, so no new secret has to be managed: the
same OS keyring entry, mounted secret file, or passphrase that unlocks the
vault also unlocks checkpoints.

Envelope layout (one per blob)::

    b"YVC" | format (1 byte) | key-id length (1 byte) | key id | nonce (12) | ciphertext+tag

Everything before the nonce is authenticated as associated data, so the key id
cannot be swapped without failing the tag check. The key id carries a version
(``v1-…``) so the key can be rotated: older versions stay readable and the
migration helpers re-encrypt rows to the active version.

Encryption is opt-in through settings (see ``checkpoint_serializer``). Once it
is on, a missing or wrong key is a hard error; nothing falls back to writing
plaintext. Legacy plaintext rows stay readable until plaintext reads are turned
off, which is the switch a product flips after running the migration.

Checkpoint *metadata* (thread ids, step counters, run tags) is stored by the
saver as plain JSON outside the serializer and is not covered here.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from yarvelle_core import identity
from yarvelle_core.vault import crypto
from yarvelle_core.vault.errors import DecryptionError, VaultError, VaultLockedError

logger = logging.getLogger(__name__)

CIPHER_NAME = "aes256gcm"
ENVELOPE_MAGIC = b"YVC"
ENVELOPE_FORMAT = 1
KEY_LENGTH = 32
_HKDF_INFO_PREFIX = b"checkpoints|v"
_KEY_ID_LABEL = b"checkpoint-key-id|"
_ENCRYPTED_SUFFIX = "+" + CIPHER_NAME

# Tables and blob columns the LangGraph SQLite savers pass through the serializer.
_SQLITE_BLOB_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("checkpoints", "checkpoint"),
    ("writes", "value"),
)


class CheckpointKeyError(VaultError):
    """The key needed for a checkpoint is missing, unknown, or misconfigured."""


class CheckpointDecryptionError(DecryptionError):
    """An encrypted checkpoint failed authentication (wrong key or tampered data)."""


class PlaintextCheckpointError(VaultError):
    """A plaintext checkpoint was read while plaintext reads are disabled."""


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckpointKey:
    """A 256-bit checkpoint key and its public identifier. ``repr`` never shows the key."""

    key_id: str
    key: bytes = field(repr=False)
    version: int = 1

    def __post_init__(self) -> None:
        if len(self.key) != KEY_LENGTH:
            raise CheckpointKeyError(f"Checkpoint key must be {KEY_LENGTH} bytes.")
        raw_id = self.key_id.encode("utf-8")
        if not raw_id or len(raw_id) > 255:
            raise CheckpointKeyError("Checkpoint key id must be 1-255 bytes.")


def checkpoint_key_id(key: bytes, version: int) -> str:
    """Public, non-secret key identifier: version plus a short fingerprint."""
    fingerprint = hashlib.sha256(_KEY_ID_LABEL + key).hexdigest()[:12]
    return f"v{version}-{fingerprint}"


def derive_checkpoint_key(kek: bytes, version: int = 1) -> CheckpointKey:
    """Derive the checkpoint key for ``version`` from the vault KEK (HKDF-SHA256).

    The salt is the app's configured vault salt and the info string names the
    purpose and version, so this key is independent of every other vault key.
    """
    if not isinstance(kek, (bytes, bytearray)) or len(kek) != KEY_LENGTH:
        raise CheckpointKeyError(f"Vault KEK must be exactly {KEY_LENGTH} bytes.")
    if not isinstance(version, int) or version < 1:
        raise CheckpointKeyError("Checkpoint key version must be an integer >= 1.")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=identity.vault_salt(),
        info=_HKDF_INFO_PREFIX + str(version).encode("ascii"),
    ).derive(bytes(kek))
    return CheckpointKey(key_id=checkpoint_key_id(key, version), key=key, version=version)


class CheckpointKeyring:
    """The active checkpoint key plus older keys that are still accepted for reads."""

    def __init__(self, active: CheckpointKey, previous: Sequence[CheckpointKey] = ()) -> None:
        self.active = active
        self._keys: Dict[str, CheckpointKey] = {k.key_id: k for k in previous}
        self._keys[active.key_id] = active

    @classmethod
    def from_kek(cls, kek: bytes, version: int = 1) -> "CheckpointKeyring":
        """Active key = ``version``; versions 1..version-1 stay readable."""
        active = derive_checkpoint_key(kek, version)
        previous = [derive_checkpoint_key(kek, v) for v in range(1, version)]
        return cls(active, previous)

    @property
    def key_ids(self) -> List[str]:
        return sorted(self._keys)

    def get(self, key_id: str) -> Optional[CheckpointKey]:
        return self._keys.get(key_id)

    def __repr__(self) -> str:  # never leak key material
        return f"CheckpointKeyring(active={self.active.key_id!r}, keys={self.key_ids!r})"


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _header(key_id: str) -> bytes:
    raw_id = key_id.encode("utf-8")
    return ENVELOPE_MAGIC + bytes([ENVELOPE_FORMAT, len(raw_id)]) + raw_id


def seal(key: CheckpointKey, plaintext: bytes) -> bytes:
    """Encrypt ``plaintext`` under ``key`` into a self-describing envelope."""
    header = _header(key.key_id)
    return header + crypto.encrypt(key.key, bytes(plaintext), header)


def envelope_key_id(blob: bytes) -> str:
    """Return the key id recorded in an envelope, or raise CheckpointDecryptionError."""
    blob = bytes(blob or b"")
    if len(blob) < 5 or blob[:3] != ENVELOPE_MAGIC:
        raise CheckpointDecryptionError("Checkpoint ciphertext has no valid envelope header.")
    if blob[3] != ENVELOPE_FORMAT:
        raise CheckpointDecryptionError(f"Unsupported checkpoint envelope format {blob[3]}.")
    id_len = blob[4]
    if len(blob) < 5 + id_len + crypto.MIN_PAYLOAD_LENGTH:
        raise CheckpointDecryptionError("Checkpoint ciphertext is truncated.")
    try:
        return blob[5 : 5 + id_len].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CheckpointDecryptionError("Checkpoint envelope key id is corrupt.") from exc


def open_envelope(keyring: CheckpointKeyring, blob: bytes) -> bytes:
    """Decrypt an envelope. Fails loudly on unknown keys or authentication failure."""
    blob = bytes(blob or b"")
    key_id = envelope_key_id(blob)
    key = keyring.get(key_id)
    if key is None:
        raise CheckpointKeyError(
            f"Checkpoint was encrypted with key {key_id}, which is not loaded "
            f"(loaded: {', '.join(keyring.key_ids)}). Wrong vault key, or a key "
            "version newer than the configured one?"
        )
    header_len = 5 + len(key_id.encode("utf-8"))
    header, payload = blob[:header_len], blob[header_len:]
    try:
        return crypto.decrypt(key.key, payload, header)
    except DecryptionError as exc:
        raise CheckpointDecryptionError(
            f"Checkpoint failed authentication under key {key_id} (tampered data or wrong key)."
        ) from exc


def is_encrypted_type(type_tag: Optional[str]) -> bool:
    return bool(type_tag) and "+" in type_tag


# ---------------------------------------------------------------------------
# LangGraph serializer
# ---------------------------------------------------------------------------


class CheckpointCipher:
    """LangGraph ``CipherProtocol`` implementation backed by a ``CheckpointKeyring``.

    It is self-contained (key lookup and authentication happen here), so even a
    plain ``EncryptedSerializer`` wrapped around it reads and writes the same format.
    """

    def __init__(self, keyring: CheckpointKeyring) -> None:
        self.keyring = keyring

    def encrypt(self, plaintext: bytes) -> Tuple[str, bytes]:
        return CIPHER_NAME, seal(self.keyring.active, plaintext)

    def decrypt(self, ciphername: str, ciphertext: bytes) -> bytes:
        if ciphername != CIPHER_NAME:
            raise CheckpointDecryptionError(f"Unsupported checkpoint cipher {ciphername!r}.")
        return open_envelope(self.keyring, ciphertext)

    def __repr__(self) -> str:
        return f"CheckpointCipher({self.keyring!r})"


class EncryptedCheckpointSerializer(EncryptedSerializer):
    """LangGraph ``EncryptedSerializer`` with an explicit plaintext-read policy.

    LangGraph's base class silently accepts any row without a cipher suffix as
    plaintext. Here that is allowed only while ``allow_plaintext_reads`` is True
    (the migration window); afterwards a plaintext row is an error.
    """

    def __init__(
        self,
        keyring: CheckpointKeyring,
        serde: Optional[Any] = None,
        *,
        allow_plaintext_reads: bool = True,
    ) -> None:
        super().__init__(CheckpointCipher(keyring), serde or JsonPlusSerializer())
        self.keyring = keyring
        self.allow_plaintext_reads = allow_plaintext_reads

    def loads_typed(self, data: Tuple[str, bytes]) -> Any:
        enc_type, payload = data
        if not is_encrypted_type(enc_type):
            if not self.allow_plaintext_reads:
                raise PlaintextCheckpointError(
                    "Found a plaintext checkpoint while plaintext reads are disabled. "
                    "Run the checkpoint migration ('checkpoints encrypt') or re-enable "
                    "plaintext reads."
                )
            return self.serde.loads_typed(data)
        typ, ciphername = enc_type.split("+", 1)
        plaintext = self.cipher.decrypt(ciphername, payload)
        return self.serde.loads_typed((typ, plaintext))

    def with_msgpack_allowlist(self, extra_allowlist: Iterable[Any]) -> "EncryptedCheckpointSerializer":
        """Mirror ``JsonPlusSerializer.with_msgpack_allowlist`` while keeping this class."""
        inner = self.serde
        if not isinstance(inner, JsonPlusSerializer):
            return self
        updated = inner.with_msgpack_allowlist(extra_allowlist)
        if updated is inner:
            return self
        clone = copy.copy(self)
        clone.serde = updated
        return clone


class PlaintextCheckpointSerializer(JsonPlusSerializer):
    """Default serializer while encryption is off; names the problem if it meets ciphertext."""

    def loads_typed(self, data: Tuple[str, bytes]) -> Any:
        if is_encrypted_type(data[0]):
            raise CheckpointKeyError(
                "Found an encrypted checkpoint but checkpoint encryption is turned off. "
                "Turn it back on, or run 'checkpoints decrypt' with the vault key first."
            )
        return super().loads_typed(data)


class EncryptionPreservingSaverMixin:
    """Keeps ``EncryptedCheckpointSerializer`` when LangGraph narrows the msgpack allowlist.

    ``BaseCheckpointSaver.with_allowlist`` rebuilds an encrypted serializer as a plain
    ``EncryptedSerializer``, which would drop the plaintext-read policy.
    """

    def with_allowlist(self, extra_allowlist):  # type: ignore[no-untyped-def]
        serde = getattr(self, "serde", None)
        if isinstance(serde, EncryptedCheckpointSerializer):
            updated = serde.with_msgpack_allowlist(extra_allowlist)
            if updated is serde:
                return self
            clone = copy.copy(self)
            clone.serde = updated
            return clone
        return super().with_allowlist(extra_allowlist)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Settings / vault wiring
# ---------------------------------------------------------------------------

_KEYRING_CACHE: Dict[int, CheckpointKeyring] = {}
_KEYRING_LOCK = threading.Lock()


def reset_checkpoint_keyring_cache() -> None:
    """Forget cached checkpoint keys (tests, or after the vault KEK changes)."""
    with _KEYRING_LOCK:
        _KEYRING_CACHE.clear()


def load_checkpoint_keyring(version: Optional[int] = None) -> CheckpointKeyring:
    """Resolve the vault KEK and derive the checkpoint keyring (cached per process).

    Raises ``CheckpointKeyError`` when the KEK cannot be resolved; there is no
    plaintext fallback.
    """
    from yarvelle_core.config import settings
    from yarvelle_core.vault.kek import get_kek

    resolved_version = int(version if version is not None else settings.checkpoint_key_version)
    with _KEYRING_LOCK:
        cached = _KEYRING_CACHE.get(resolved_version)
        if cached is not None:
            return cached
        try:
            kek = get_kek()
        except VaultLockedError as exc:
            raise CheckpointKeyError(
                "Checkpoint encryption needs the vault key, but it could not be resolved "
                f"({exc}). Unlock the vault (OS keyring, {identity.env_name('VAULT_KEK_FILE')} "
                f"or {identity.env_name('VAULT_PASSPHRASE')}) or turn checkpoint encryption off."
            ) from exc
        keyring = CheckpointKeyring.from_kek(kek, resolved_version)
        _KEYRING_CACHE[resolved_version] = keyring
        return keyring


def checkpoint_encryption_enabled() -> bool:
    from yarvelle_core.config import settings

    return bool(settings.checkpoint_encryption)


def checkpoint_serializer(
    keyring: Optional[CheckpointKeyring] = None,
) -> Union[EncryptedCheckpointSerializer, PlaintextCheckpointSerializer]:
    """Serializer for checkpoint savers according to settings.

    Encryption off: a plaintext serializer that refuses ciphertext with a clear message.
    Encryption on: an encrypted serializer keyed from the vault (fails if the key is missing).
    """
    from yarvelle_core.config import settings

    if not settings.checkpoint_encryption and keyring is None:
        return PlaintextCheckpointSerializer()
    return EncryptedCheckpointSerializer(
        keyring or load_checkpoint_keyring(),
        allow_plaintext_reads=bool(settings.checkpoint_plaintext_reads),
    )


# ---------------------------------------------------------------------------
# Migration of SQLite checkpoint databases
# ---------------------------------------------------------------------------


@dataclass
class CheckpointMigrationReport:
    """Row counts before (and, unless dry-run, after) a migration pass."""

    db_path: str
    action: str
    dry_run: bool
    plaintext_rows: int = 0
    active_key_rows: int = 0
    other_key_rows: Dict[str, int] = field(default_factory=dict)
    rows_changed: int = 0
    backup_path: Optional[str] = None

    @property
    def encrypted_rows(self) -> int:
        return self.active_key_rows + sum(self.other_key_rows.values())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "db_path": self.db_path,
            "action": self.action,
            "dry_run": self.dry_run,
            "plaintext_rows": self.plaintext_rows,
            "active_key_rows": self.active_key_rows,
            "other_key_rows": dict(self.other_key_rows),
            "rows_changed": self.rows_changed,
            "backup_path": self.backup_path,
        }


def _existing_blob_columns(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return [(t, c) for t, c in _SQLITE_BLOB_COLUMNS if t in names]


def _iter_rows(conn: sqlite3.Connection, table: str, column: str):
    cursor = conn.execute(f"SELECT rowid, type, {column} FROM {table}")  # noqa: S608 - fixed names
    for rowid, type_tag, blob in cursor:
        yield rowid, type_tag, (bytes(blob) if blob is not None else None)


def backup_sqlite_db(db_path: Union[str, Path]) -> Path:
    """Consistent copy of the DB (including WAL content) next to it, before any rewrite."""
    src = Path(db_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = src.with_name(f"{src.name}.bak-{stamp}")
    with sqlite3.connect(str(src)) as source, sqlite3.connect(str(dest)) as target:
        source.backup(target)
    return dest


def _scan(conn: sqlite3.Connection, keyring: CheckpointKeyring, report: CheckpointMigrationReport) -> None:
    for table, column in _existing_blob_columns(conn):
        for _rowid, type_tag, blob in _iter_rows(conn, table, column):
            if type_tag is None:
                continue
            if not is_encrypted_type(type_tag):
                report.plaintext_rows += 1
                continue
            key_id = envelope_key_id(blob or b"")
            if key_id == keyring.active.key_id:
                report.active_key_rows += 1
            else:
                report.other_key_rows[key_id] = report.other_key_rows.get(key_id, 0) + 1


def _require_db(db_path: Union[str, Path]) -> Path:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint database not found: {path}")
    return path


def checkpoint_db_status(db_path: Union[str, Path], keyring: CheckpointKeyring) -> CheckpointMigrationReport:
    """Count plaintext rows, rows under the active key, and rows under other keys."""
    path = _require_db(db_path)
    report = CheckpointMigrationReport(db_path=str(path), action="status", dry_run=True)
    with sqlite3.connect(str(path)) as conn:
        _scan(conn, keyring, report)
    return report


def _compact(conn: sqlite3.Connection) -> None:
    """Rebuild the file and fold the WAL back in, dropping stale copies of old rows."""
    try:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as exc:  # e.g. another connection holds the DB open
        logger.warning(
            "Checkpoint migration committed, but compacting the database failed (%s). "
            "Run VACUUM when the app is stopped so old row contents are not left in free pages.",
            exc,
        )


def _migrate(
    db_path: Union[str, Path],
    keyring: CheckpointKeyring,
    *,
    action: str,
    dry_run: bool,
    backup: bool,
) -> CheckpointMigrationReport:
    path = _require_db(db_path)
    report = CheckpointMigrationReport(db_path=str(path), action=action, dry_run=dry_run)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    try:
        _scan(conn, keyring, report)
        if action == "encrypt":
            pending = report.plaintext_rows + sum(report.other_key_rows.values())
        else:
            pending = report.encrypted_rows
        if dry_run:
            report.rows_changed = pending  # rows that would change
            return report
        if pending == 0:
            return report
        if backup:
            report.backup_path = str(backup_sqlite_db(path))
        # Overwrite freed pages so replaced plaintext does not linger in the file.
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            changed = 0
            for table, column in _existing_blob_columns(conn):
                updates: List[Tuple[str, Optional[bytes], int]] = []
                for rowid, type_tag, blob in list(_iter_rows(conn, table, column)):
                    if type_tag is None:
                        continue
                    if action == "encrypt":
                        if not is_encrypted_type(type_tag):
                            new_type = type_tag + _ENCRYPTED_SUFFIX
                            new_blob = seal(keyring.active, blob or b"")
                        else:
                            if envelope_key_id(blob or b"") == keyring.active.key_id:
                                continue
                            base_type = type_tag.split("+", 1)[0]
                            plaintext = open_envelope(keyring, blob or b"")
                            new_type = base_type + _ENCRYPTED_SUFFIX
                            new_blob = seal(keyring.active, plaintext)
                    else:
                        if not is_encrypted_type(type_tag):
                            continue
                        base_type, ciphername = type_tag.split("+", 1)
                        if ciphername != CIPHER_NAME:
                            raise CheckpointDecryptionError(
                                f"Unsupported checkpoint cipher {ciphername!r} in {table}."
                            )
                        new_type = base_type
                        new_blob = open_envelope(keyring, blob or b"")
                    updates.append((new_type, new_blob, rowid))
                conn.executemany(
                    f"UPDATE {table} SET type = ?, {column} = ? WHERE rowid = ?",  # noqa: S608
                    updates,
                )
                changed += len(updates)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        report.rows_changed = changed
        _compact(conn)
        return report
    finally:
        conn.close()


def encrypt_checkpoint_db(
    db_path: Union[str, Path],
    keyring: CheckpointKeyring,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> CheckpointMigrationReport:
    """Encrypt plaintext rows and re-encrypt rows under older keys. Idempotent.

    Runs in one transaction; a failure leaves the database unchanged. A backup
    copy is written next to the DB first unless ``backup`` is False; that copy
    still holds plaintext, so delete it once the migrated DB has been checked.
    Afterwards the file is vacuumed so replaced plaintext is not left in free pages.
    """
    return _migrate(db_path, keyring, action="encrypt", dry_run=dry_run, backup=backup)


def decrypt_checkpoint_db(
    db_path: Union[str, Path],
    keyring: CheckpointKeyring,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> CheckpointMigrationReport:
    """Reverse path: turn every encrypted row back into plaintext. Idempotent."""
    return _migrate(db_path, keyring, action="decrypt", dry_run=dry_run, backup=backup)


__all__ = [
    "CIPHER_NAME",
    "CheckpointCipher",
    "CheckpointDecryptionError",
    "CheckpointKey",
    "CheckpointKeyError",
    "CheckpointKeyring",
    "CheckpointMigrationReport",
    "EncryptedCheckpointSerializer",
    "EncryptionPreservingSaverMixin",
    "PlaintextCheckpointError",
    "PlaintextCheckpointSerializer",
    "backup_sqlite_db",
    "checkpoint_db_status",
    "checkpoint_encryption_enabled",
    "checkpoint_key_id",
    "checkpoint_serializer",
    "decrypt_checkpoint_db",
    "derive_checkpoint_key",
    "encrypt_checkpoint_db",
    "is_encrypted_type",
    "load_checkpoint_keyring",
    "open_envelope",
    "reset_checkpoint_keyring_cache",
    "seal",
]
