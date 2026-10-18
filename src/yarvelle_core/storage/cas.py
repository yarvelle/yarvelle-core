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

"""Content-Addressed Storage (CAS) engine.

Enforces storage layout:
    <yarvelle_home>/data/files/<user_id>/<profile_id>/<sha256>

Provides per-profile deduplication and strictly scoped cryptographic storage.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Optional, Tuple
import uuid

from yarvelle_core.logging import get_logger
from yarvelle_core.scope.context import DEFAULT_SCOPE

logger = get_logger("yarvelle_core.storage.cas")

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
DANGEROUS_CHARS_REGEX = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize_partition_segment(segment: Optional[str], default: str = "default") -> str:
    """Sanitizes user or profile identifiers to ensure sandbox containment."""
    if not segment or not str(segment).strip():
        return default
    raw = str(segment).strip()
    if "/" in raw or "\\" in raw or "\0" in raw or ".." in raw:
        raise ValueError(f"Invalid partition identifier containing traversal sequences: '{segment}'")
    cleaned = DANGEROUS_CHARS_REGEX.sub("_", raw)
    if cleaned in ("", ".", ".."):
        return default
    return cleaned


def get_cas_path(
    yarvelle_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Path:
    """Computes the canonical Content-Addressed Storage path for an attachment.

    Hierarchy:
        <yarvelle_home>/data/files/<user_id>/<profile_id>/<scope>/<sha256>
    or legacy (when scope is None):
        <yarvelle_home>/data/files/<user_id>/<profile_id>/<sha256>
    """
    clean_uid = sanitize_partition_segment(user_id)
    clean_pid = sanitize_partition_segment(profile_id)
    clean_hash = str(sha256_hash).strip().lower()

    if not SHA256_HEX_REGEX.match(clean_hash):
        raise ValueError(f"Invalid SHA-256 digest format: '{sha256_hash}'")

    if scope is None:
        return yarvelle_home.resolve() / "data" / "files" / clean_uid / clean_pid / clean_hash

    clean_scope = sanitize_partition_segment(scope, default=DEFAULT_SCOPE)
    return yarvelle_home.resolve() / "data" / "files" / clean_uid / clean_pid / clean_scope / clean_hash


def resolve_cas_path(
    yarvelle_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Path:
    """Resolves existing CAS file with fallback to legacy path for default scope."""
    scoped_path = get_cas_path(yarvelle_home, user_id, profile_id, sha256_hash, scope=scope)
    if scoped_path.is_file():
        return scoped_path

    # Fallback to legacy path for default domain
    if scope is None or scope == DEFAULT_SCOPE or scope.startswith(f"{DEFAULT_SCOPE}."):
        legacy_path = get_cas_path(yarvelle_home, user_id, profile_id, sha256_hash, scope=None)
        if legacy_path.is_file():
            return legacy_path

    return scoped_path


def cas_file_exists(
    yarvelle_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> bool:
    """Checks whether the specified content-addressed file exists on disk."""
    try:
        path = resolve_cas_path(yarvelle_home, user_id, profile_id, sha256_hash, scope=scope)
        return path.is_file()
    except ValueError:
        return False


def store_cas_file(
    content: bytes,
    yarvelle_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: Optional[str] = None,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> Tuple[Path, str, bool]:
    """Stores content in canonical CAS layout with per-profile, per-scope deduplication.

    Returns:
        Tuple of (canonical_path, sha256_digest, is_deduplicated).
    """
    if sha256_hash is None:
        computed_hash = hashlib.sha256(content).hexdigest().lower()
    else:
        computed_hash = str(sha256_hash).strip().lower()

    canonical_path = get_cas_path(yarvelle_home, user_id, profile_id, computed_hash, scope=scope)

    # Scoped deduplication: if exact CAS file exists within this scope partition, skip rewrite
    if canonical_path.is_file() and canonical_path.stat().st_size == len(content):
        logger.debug(
            "cas_deduplication_hit",
            path=str(canonical_path),
            sha256=computed_hash[:8],
            user_id=user_id,
            profile_id=profile_id,
            scope=scope,
        )
        return canonical_path, computed_hash, True

    # Ensure parent partition exists
    canonical_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write via temporary file
    temp_name = f".{computed_hash}.{uuid.uuid4().hex}.tmp"
    temp_path = canonical_path.parent / temp_name

    try:
        temp_path.write_bytes(content)
        os.replace(temp_path, canonical_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    logger.info(
        "cas_file_stored",
        path=str(canonical_path),
        size=len(content),
        sha256=computed_hash[:8],
        user_id=user_id,
        profile_id=profile_id,
        scope=scope,
    )
    return canonical_path, computed_hash, False


def read_cas_file(
    yarvelle_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    scope: Optional[str] = DEFAULT_SCOPE,
) -> bytes:
    """Reads content from CAS storage, raising FileNotFoundError if missing."""
    canonical_path = resolve_cas_path(yarvelle_home, user_id, profile_id, sha256_hash, scope=scope)
    if not canonical_path.is_file():
        raise FileNotFoundError(f"CAS file '{sha256_hash}' not found at {canonical_path}")
    return canonical_path.read_bytes()


__all__ = [
    "get_cas_path",
    "resolve_cas_path",
    "cas_file_exists",
    "store_cas_file",
    "read_cas_file",
    "sanitize_partition_segment",
]
