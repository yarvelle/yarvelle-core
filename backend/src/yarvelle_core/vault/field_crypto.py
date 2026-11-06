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

"""Opt-in at-rest field encryption for audit bodies and long-term memory.

Reuses the vault AES-256-GCM primitive and HKDF key derivation pattern from
checkpoint encryption. Purpose-scoped keys (audit vs memory) are derived from
the application vault KEK; envelopes bind AAD so ciphertext cannot be moved
across profiles, namespaces, or record ids.

Text columns store ``enc:v1:`` + urlsafe-base64(envelope). Binary callers may
use the raw envelope helpers directly. Encryption is opt-in via settings;
defaults preserve plaintext behavior.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import logging
from typing import Dict, Iterable, List, Optional, Sequence

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from yarvelle_core import identity
from yarvelle_core.vault import crypto
from yarvelle_core.vault.errors import DecryptionError, VaultError

logger = logging.getLogger(__name__)

ENVELOPE_MAGIC = b"YVF"
ENVELOPE_FORMAT = 1
KEY_LENGTH = 32
TEXT_PREFIX = "enc:v1:"
PURPOSE_AUDIT = "audit"
PURPOSE_MEMORY = "memory"

_HKDF_INFO_PREFIX = b"field|"
_KEY_ID_LABEL = b"field-key-id|"


class FieldKeyError(VaultError):
    """The key needed for a sealed field is missing, unknown, or misconfigured."""


class FieldDecryptionError(DecryptionError):
    """A sealed field failed authentication (wrong key, AAD, or tampered data)."""


class PlaintextFieldError(VaultError):
    """A plaintext field was read while plaintext reads are disabled."""


@dataclass(frozen=True)
class FieldKey:
    """A 256-bit field key and public identifier. ``repr`` never shows the key."""

    key_id: str
    key: bytes = field(repr=False)
    purpose: str = PURPOSE_AUDIT
    version: int = 1

    def __post_init__(self) -> None:
        if len(self.key) != KEY_LENGTH:
            raise FieldKeyError(f"Field key must be {KEY_LENGTH} bytes.")
        raw_id = self.key_id.encode("utf-8")
        if not raw_id or len(raw_id) > 255:
            raise FieldKeyError("Field key id must be 1-255 bytes.")


def field_key_id(key: bytes, purpose: str, version: int) -> str:
    fingerprint = hashlib.sha256(_KEY_ID_LABEL + purpose.encode("utf-8") + b"|" + key).hexdigest()[:12]
    return f"{purpose}-v{version}-{fingerprint}"


def derive_field_key(kek: bytes, purpose: str, version: int = 1) -> FieldKey:
    if not isinstance(kek, (bytes, bytearray)) or len(kek) != KEY_LENGTH:
        raise FieldKeyError(f"Vault KEK must be exactly {KEY_LENGTH} bytes.")
    if purpose not in (PURPOSE_AUDIT, PURPOSE_MEMORY):
        raise FieldKeyError(f"Unsupported field encryption purpose: {purpose!r}")
    if not isinstance(version, int) or version < 1:
        raise FieldKeyError("Field key version must be an integer >= 1.")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=identity.vault_salt(),
        info=_HKDF_INFO_PREFIX + purpose.encode("ascii") + b"|v" + str(version).encode("ascii"),
    ).derive(bytes(kek))
    return FieldKey(
        key_id=field_key_id(key, purpose, version),
        key=key,
        purpose=purpose,
        version=version,
    )


class FieldKeyring:
    """Active field key plus older versions still accepted for reads."""

    def __init__(self, active: FieldKey, previous: Sequence[FieldKey] = ()) -> None:
        self.active = active
        self._keys: Dict[str, FieldKey] = {k.key_id: k for k in previous}
        self._keys[active.key_id] = active

    @classmethod
    def from_kek(cls, kek: bytes, purpose: str, version: int = 1) -> "FieldKeyring":
        active = derive_field_key(kek, purpose, version)
        previous = [derive_field_key(kek, purpose, v) for v in range(1, version)]
        return cls(active, previous)

    @property
    def key_ids(self) -> List[str]:
        return sorted(self._keys)

    def get(self, key_id: str) -> Optional[FieldKey]:
        return self._keys.get(key_id)


def _header(key_id: str) -> bytes:
    raw_id = key_id.encode("utf-8")
    return ENVELOPE_MAGIC + bytes([ENVELOPE_FORMAT, len(raw_id)]) + raw_id


def seal(key: FieldKey, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt plaintext into a self-describing envelope.

    The envelope header is authenticated together with caller AAD so both the
    key id and the semantic binding (profile/namespace/id) are covered.
    """
    header = _header(key.key_id)
    bound = header + b"|" + bytes(aad)
    return header + crypto.encrypt(key.key, bytes(plaintext), bound)


def envelope_key_id(blob: bytes) -> str:
    blob = bytes(blob or b"")
    if len(blob) < 5 or blob[:3] != ENVELOPE_MAGIC:
        raise FieldDecryptionError("Field ciphertext has no valid envelope header.")
    if blob[3] != ENVELOPE_FORMAT:
        raise FieldDecryptionError(f"Unsupported field envelope format {blob[3]}.")
    id_len = blob[4]
    if len(blob) < 5 + id_len + crypto.MIN_PAYLOAD_LENGTH:
        raise FieldDecryptionError("Field ciphertext is truncated.")
    try:
        return blob[5 : 5 + id_len].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FieldDecryptionError("Field envelope key id is corrupt.") from exc


def open_envelope(keyring: FieldKeyring, blob: bytes, aad: bytes) -> bytes:
    blob = bytes(blob or b"")
    key_id = envelope_key_id(blob)
    key = keyring.get(key_id)
    if key is None:
        raise FieldKeyError(
            f"Field was encrypted with key {key_id}, which is not loaded "
            f"(loaded: {', '.join(keyring.key_ids)})."
        )
    header_len = 5 + len(key_id.encode("utf-8"))
    header, payload = blob[:header_len], blob[header_len:]
    bound = header + b"|" + bytes(aad)
    try:
        return crypto.decrypt(key.key, payload, bound)
    except DecryptionError as exc:
        raise FieldDecryptionError(
            f"Field failed authentication under key {key_id} (tampered data, wrong key, or AAD mismatch)."
        ) from exc


def is_sealed_text(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(TEXT_PREFIX)


def seal_text(keyring: FieldKeyring, plaintext: str, aad: bytes) -> str:
    blob = seal(keyring.active, plaintext.encode("utf-8"), aad)
    return TEXT_PREFIX + base64.urlsafe_b64encode(blob).decode("ascii")


def open_text(
    keyring: FieldKeyring,
    value: Optional[str],
    aad: bytes,
    *,
    allow_plaintext: bool,
) -> Optional[str]:
    if value is None:
        return None
    if not is_sealed_text(value):
        if not allow_plaintext:
            raise PlaintextFieldError(
                "Found a plaintext field while plaintext reads are disabled. "
                "Migrate existing rows or re-enable plaintext reads."
            )
        return value
    raw = value[len(TEXT_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception as exc:
        raise FieldDecryptionError("Field ciphertext encoding is corrupt.") from exc
    try:
        return open_envelope(keyring, blob, aad).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FieldDecryptionError("Field plaintext is not valid UTF-8 (tampered or wrong key).") from exc


def build_aad(parts: Iterable[object]) -> bytes:
    """Canonical AAD binding: join stringified parts with ``|`` (empty for None)."""
    return "|".join("" if p is None else str(p) for p in parts).encode("utf-8")


_keyring_cache: Dict[tuple, FieldKeyring] = {}


def reset_field_keyring_cache() -> None:
    _keyring_cache.clear()


def _cache_key(kek: bytes, purpose: str, version: int) -> tuple:
    return (hashlib.sha256(bytes(kek)).digest(), purpose, int(version))


def get_audit_keyring(*, kek: Optional[bytes] = None, version: Optional[int] = None) -> FieldKeyring:
    from yarvelle_core.config import settings
    from yarvelle_core.vault.kek import get_kek

    material = kek if kek is not None else get_kek()
    ver = version if version is not None else int(getattr(settings, "audit_key_version", 1))
    key = _cache_key(material, PURPOSE_AUDIT, ver)
    ring = _keyring_cache.get(key)
    if ring is None:
        ring = FieldKeyring.from_kek(material, PURPOSE_AUDIT, ver)
        if kek is None:
            _keyring_cache[key] = ring
    return ring


def get_memory_keyring(*, kek: Optional[bytes] = None, version: Optional[int] = None) -> FieldKeyring:
    from yarvelle_core.config import settings
    from yarvelle_core.vault.kek import get_kek

    material = kek if kek is not None else get_kek()
    ver = version if version is not None else int(getattr(settings, "memory_key_version", 1))
    key = _cache_key(material, PURPOSE_MEMORY, ver)
    ring = _keyring_cache.get(key)
    if ring is None:
        ring = FieldKeyring.from_kek(material, PURPOSE_MEMORY, ver)
        if kek is None:
            _keyring_cache[key] = ring
    return ring
