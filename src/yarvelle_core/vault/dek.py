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

"""Profile Data Encryption Key (DEK) lifecycle, AAD credential encryption, and crypto-shredding.

Implements Milestone 2 Focus Area 2 (AU-14 / ADR-0005):
- 256-bit unique DEK generation per care profile (os.urandom(32)).
- Envelope encryption of DEK under master KEK using AES-256-GCM.
- Cryptographic Additional Authenticated Data (AAD) binding to (profile_id, connection_id, dek_version).
- O(1) crypto-shredding: deleting a profile cascades to profile_keys, permanently destroying the DEK.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import os
from typing import Optional, Tuple, Union
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from yarvelle_core.db.models import ProfileKey
from yarvelle_core.scope.context import DEFAULT_SCOPE, require_scope
from yarvelle_core.vault.crypto import decrypt, encrypt
from yarvelle_core.vault.errors import DecryptionError, VaultLockedError
from yarvelle_core.vault.kek import DEFAULT_ARGON2_SALT

DEK_LENGTH_BYTES = 32  # 256-bit AES key
DEFAULT_DEK_VERSION = 1


def _extract_bytes(data: Union[str, bytes, bytearray]) -> bytes:
    """Helper converting hex, base64, or string representations to raw bytes."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        try:
            return bytes.fromhex(data)
        except ValueError:
            try:
                return base64.b64decode(data)
            except Exception:
                return data.encode("utf-8")
    return bytes(data)


def compute_aad_binding(profile_id: str, connection_id: str, dek_version: int) -> bytes:
    """Computes Authenticated Additional Data (AAD) for credential encryption.

    Binds the ciphertext cryptographically to the exact (profile_id, connection_id, dek_version)
    tuple to prevent row-copying or cross-profile relocation attacks.
    """
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")
    if not connection_id or not isinstance(connection_id, str) or not connection_id.strip():
        raise ValueError("connection_id must be a non-empty string")
    if dek_version < 1:
        raise ValueError(f"dek_version must be >= 1, got {dek_version}")
    return f"{profile_id.strip()}|{connection_id.strip()}|{dek_version}".encode("utf-8")


def compute_dek_wrapping_aad(profile_id: str, dek_version: int) -> bytes:
    """Computes AAD for wrapping the profile DEK under the master KEK."""
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")
    if dek_version < 1:
        raise ValueError(f"dek_version must be >= 1, got {dek_version}")
    return f"{profile_id.strip()}|profile_dek|{dek_version}".encode("utf-8")


async def get_or_create_dek(
    db: AsyncSession,
    profile_id: str,
    kek: bytes,
) -> Tuple[bytes, int]:
    """Retrieves and decrypts the profile DEK, or creates and stores a new one.

    Args:
        db: Active SQLAlchemy AsyncSession.
        profile_id: Care profile identifier.
        kek: 32-byte master Key Encryption Key.

    Returns:
        Tuple of (raw_dek_bytes, dek_version).

    Raises:
        VaultLockedError: If KEK is invalid or missing.
        DecryptionError: If encrypted DEK is corrupted or KEK mismatch occurs.
        ValueError: If profile_id is invalid.
    """
    if not isinstance(kek, (bytes, bytearray)) or len(kek) != DEK_LENGTH_BYTES:
        raise VaultLockedError(
            f"Master KEK must be exactly {DEK_LENGTH_BYTES} bytes, got "
            f"{len(kek) if isinstance(kek, (bytes, bytearray)) else type(kek)}"
        )
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")

    clean_profile_id = profile_id.strip()

    # 1. Look up existing profile key
    stmt = select(ProfileKey).where(ProfileKey.profile_id == clean_profile_id)
    res = await db.execute(stmt)
    existing_key = res.scalar_one_or_none()

    if existing_key is not None:
        aad = compute_dek_wrapping_aad(clean_profile_id, existing_key.dek_version)
        enc_bytes = _extract_bytes(existing_key.encrypted_dek)
        try:
            raw_dek = decrypt(bytes(kek), enc_bytes, aad)
        except DecryptionError:
            # Fallback to empty AAD for backwards compatibility
            try:
                raw_dek = decrypt(bytes(kek), enc_bytes, b"")
            except Exception as exc:
                raise DecryptionError(
                    f"Failed to decrypt DEK for profile '{clean_profile_id}': authentication tag verification failed"
                ) from exc
        return raw_dek, existing_key.dek_version

    # 2. Key does not exist: generate fresh 256-bit DEK
    raw_dek = os.urandom(DEK_LENGTH_BYTES)
    dek_version = DEFAULT_DEK_VERSION
    aad = compute_dek_wrapping_aad(clean_profile_id, dek_version)
    encrypted_dek = encrypt(bytes(kek), raw_dek, aad)

    now = datetime.now(timezone.utc)
    new_record = ProfileKey(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        encrypted_dek=encrypted_dek.hex(),
        dek_version=dek_version,
        created_at=now,
        updated_at=now,
    )

    try:
        db.add(new_record)
        await db.commit()
        await db.refresh(new_record)
    except Exception:
        await db.rollback()
        # Handle concurrent insertion race
        retry_res = await db.execute(stmt)
        existing = retry_res.scalar_one_or_none()
        if existing is not None:
            aad = compute_dek_wrapping_aad(clean_profile_id, existing.dek_version)
            enc_bytes = _extract_bytes(existing.encrypted_dek)
            try:
                raw_dek = decrypt(bytes(kek), enc_bytes, aad)
            except DecryptionError:
                raw_dek = decrypt(bytes(kek), enc_bytes, b"")
            return raw_dek, existing.dek_version
        raise

    return raw_dek, dek_version


def encrypt_credential(
    dek: bytes,
    payload: Union[bytes, str],
    profile_id: str,
    connection_id: str,
    dek_version: int,
) -> bytes:
    """Encrypts connection credential payload using profile DEK bound to profile_id, connection_id, and dek_version.

    Args:
        dek: 32-byte Data Encryption Key for the profile.
        payload: Plaintext credential bytes (or string) to encrypt.
        profile_id: Profile UUID string.
        connection_id: Connection UUID string.
        dek_version: DEK version integer.

    Returns:
        Ciphertext payload bytes: nonce (12B) || ciphertext (NB) || tag (16B).

    Raises:
        ValueError: If arguments are invalid.
    """
    if not isinstance(dek, (bytes, bytearray)) or len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be exactly {DEK_LENGTH_BYTES} bytes")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError(f"payload must be bytes or str, got {type(payload)}")

    aad = compute_aad_binding(profile_id, connection_id, dek_version)
    return encrypt(bytes(dek), bytes(payload), aad)


def decrypt_credential(
    dek: bytes,
    ciphertext: Union[bytes, str],
    profile_id: str,
    connection_id: str,
    dek_version: int,
) -> bytes:
    """Decrypts connection credential payload asserting cryptographic AAD binding.

    Args:
        dek: 32-byte Data Encryption Key for the profile.
        ciphertext: Encrypted payload bytes (or hex / base64 string).
        profile_id: Profile UUID string.
        connection_id: Connection UUID string.
        dek_version: DEK version integer.

    Returns:
        Plaintext credential bytes.

    Raises:
        DecryptionError: If ciphertext is corrupted, wrong key used, or AAD mismatch occurs.
        ValueError: If arguments are invalid.
    """
    if not isinstance(dek, (bytes, bytearray)) or len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be exactly {DEK_LENGTH_BYTES} bytes")

    raw_ct = _extract_bytes(ciphertext)
    aad = compute_aad_binding(profile_id, connection_id, dek_version)
    return decrypt(bytes(dek), raw_ct, aad)


async def rotate_dek(
    db: AsyncSession,
    profile_id: str,
    kek: bytes,
) -> Tuple[bytes, int]:
    """Rotates profile DEK: generates new 256-bit key, increments version, and updates database."""
    if not isinstance(kek, (bytes, bytearray)) or len(kek) != DEK_LENGTH_BYTES:
        raise VaultLockedError(f"Master KEK must be exactly {DEK_LENGTH_BYTES} bytes")
    if not profile_id or not isinstance(profile_id, str):
        raise ValueError("profile_id must be a non-empty string")

    clean_profile_id = profile_id.strip()
    stmt = select(ProfileKey).where(ProfileKey.profile_id == clean_profile_id)
    res = await db.execute(stmt)
    key_record = res.scalar_one_or_none()

    new_version = (key_record.dek_version + 1) if key_record is not None else DEFAULT_DEK_VERSION
    new_raw_dek = os.urandom(DEK_LENGTH_BYTES)
    aad = compute_dek_wrapping_aad(clean_profile_id, new_version)
    new_encrypted_dek = encrypt(bytes(kek), new_raw_dek, aad)

    now = datetime.now(timezone.utc)
    if key_record is not None:
        key_record.encrypted_dek = new_encrypted_dek.hex()
        key_record.dek_version = new_version
        key_record.updated_at = now
    else:
        key_record = ProfileKey(
            id=str(uuid.uuid4()),
            profile_id=clean_profile_id,
            encrypted_dek=new_encrypted_dek.hex(),
            dek_version=new_version,
            created_at=now,
            updated_at=now,
        )
        db.add(key_record)

    await db.commit()
    await db.refresh(key_record)
    return new_raw_dek, new_version


async def delete_profile_keys(
    db: AsyncSession,
    profile_id: str,
) -> bool:
    """Manually deletes the profile DEK from database, executing instant crypto-shredding.

    Returns:
        True if key was deleted, False if no key existed.
    """
    if not profile_id or not isinstance(profile_id, str):
        raise ValueError("profile_id must be a non-empty string")

    clean_profile_id = profile_id.strip()
    stmt = select(ProfileKey).where(ProfileKey.profile_id == clean_profile_id)
    res = await db.execute(stmt)
    key_record = res.scalar_one_or_none()
    if key_record is None:
        return False

    await db.delete(key_record)
    await db.commit()
    return True


def derive_scope_dek(profile_dek: bytes, scope: str) -> bytes:
    """Derives a scope-isolated Data Encryption Key (DEK) from the master profile DEK.

    For backwards compatibility, the legacy default scope returns profile_dek directly.
    For all other scopes (e.g. 'finance', 'education'), derives a distinct 256-bit sub-key
    using HKDF-SHA256 with DEFAULT_ARGON2_SALT and info=b"scope:<clean_scope>".
    """
    if not isinstance(profile_dek, (bytes, bytearray)) or len(profile_dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"profile_dek must be exactly {DEK_LENGTH_BYTES} bytes")
    if not scope or not isinstance(scope, str) or not scope.strip():
        raise ValueError("scope must be a non-empty string")

    clean_scope = scope.strip()
    if clean_scope == DEFAULT_SCOPE:
        return bytes(profile_dek)

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=DEK_LENGTH_BYTES,
        salt=DEFAULT_ARGON2_SALT,
        info=f"scope:{clean_scope}".encode("utf-8"),
    )
    return hkdf.derive(bytes(profile_dek))


def compute_scope_aad(profile_id: str, connection_id: str, dek_version: int, scope: str) -> bytes:
    """Computes Authenticated Additional Data (AAD) for scoped credential encryption."""
    base_aad = compute_aad_binding(profile_id, connection_id, dek_version)
    clean_scope = (scope or DEFAULT_SCOPE).strip()
    if clean_scope == DEFAULT_SCOPE:
        return base_aad
    return f"{base_aad.decode('utf-8')}|scope:{clean_scope}".encode("utf-8")


def encrypt_scoped_credential(
    dek: bytes,
    payload: Union[bytes, str],
    profile_id: str,
    connection_id: str,
    dek_version: int,
    scope: str = DEFAULT_SCOPE,
) -> bytes:
    """Encrypts credential asserting cryptographic AAD binding including domain scope."""
    if not isinstance(dek, (bytes, bytearray)) or len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be exactly {DEK_LENGTH_BYTES} bytes")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError(f"payload must be bytes or str, got {type(payload)}")

    aad = compute_scope_aad(profile_id, connection_id, dek_version, scope)
    return encrypt(bytes(dek), bytes(payload), aad)


def decrypt_scoped_credential(
    dek: bytes,
    ciphertext: Union[bytes, str],
    profile_id: str,
    connection_id: str,
    dek_version: int,
    scope: str = DEFAULT_SCOPE,
) -> bytes:
    """Decrypts credential asserting cryptographic AAD binding including domain scope."""
    if not isinstance(dek, (bytes, bytearray)) or len(dek) != DEK_LENGTH_BYTES:
        raise ValueError(f"DEK must be exactly {DEK_LENGTH_BYTES} bytes")

    raw_ct = _extract_bytes(ciphertext)
    aad = compute_scope_aad(profile_id, connection_id, dek_version, scope)
    return decrypt(bytes(dek), raw_ct, aad)


class ScopedVault:
    """Per-profile, per-scope cryptographic vault wrapping AES-256-GCM."""

    def __init__(self, profile_id: str, scope: str, scope_dek: bytes, dek_version: int):
        if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("profile_id must be a non-empty string")
        if not scope or not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if not isinstance(scope_dek, (bytes, bytearray)) or len(scope_dek) != DEK_LENGTH_BYTES:
            raise ValueError(f"scope_dek must be exactly {DEK_LENGTH_BYTES} bytes")
        if dek_version < 1:
            raise ValueError(f"dek_version must be >= 1, got {dek_version}")

        self.profile_id = profile_id.strip()
        self.scope = scope.strip()
        self.scope_dek = bytes(scope_dek)
        self.dek_version = dek_version

    def encrypt(self, payload: Union[bytes, str], connection_id: str) -> bytes:
        aad = compute_scope_aad(self.profile_id, connection_id, self.dek_version, self.scope)
        return encrypt(self.scope_dek, payload, aad)

    def decrypt(self, ciphertext: Union[bytes, str], connection_id: str) -> bytes:
        raw_ct = _extract_bytes(ciphertext)
        aad = compute_scope_aad(self.profile_id, connection_id, self.dek_version, self.scope)
        return decrypt(self.scope_dek, raw_ct, aad)


async def get_vault_for_scope(
    db: AsyncSession,
    profile_id: str,
    scope: str,
    kek: bytes,
) -> ScopedVault:
    """Retrieves or derives a ScopedVault instance for the specified profile and scope.

    Enforces that caller's active ScopeContext grants access to the requested scope.
    """
    clean_scope = (scope or DEFAULT_SCOPE).strip()
    require_scope(clean_scope)

    clean_profile_id = profile_id.strip()
    raw_dek, dek_version = await get_or_create_dek(db, clean_profile_id, kek)
    scope_dek = derive_scope_dek(raw_dek, clean_scope)
    return ScopedVault(
        profile_id=clean_profile_id,
        scope=clean_scope,
        scope_dek=scope_dek,
        dek_version=dek_version,
    )

