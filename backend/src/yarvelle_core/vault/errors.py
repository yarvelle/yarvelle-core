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

"""Yarvelle Core Vault Exception Hierarchy.

Defines domain-specific errors for the cryptographic keyring vault bridged onto
the unified ``YarvelleError`` taxonomy (``YRV-400-*``), ensuring fail-closed
semantics and zero-silent-plaintext leaks.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yarvelle_core.errors.base import YarvelleError


class VaultError(YarvelleError):
    """Base exception for all Yarvelle Core cryptographic vault operations."""

    DEFAULT_ERROR_CODE = "YRV-400-001"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            code or self.DEFAULT_ERROR_CODE,
            context=context,
            cause=cause,
            detail=str(message) if message is not None else None,
        )


class VaultLockedError(VaultError):
    """Raised when the master Key Encryption Key (KEK) is missing, empty, or inaccessible.

    Yarvelle Core strictly enforces a fail-closed policy: under no circumstance will the runtime
    silently fall back to unencrypted storage or a hardcoded default key.
    """

    DEFAULT_ERROR_CODE = "YRV-400-002"


class DecryptionError(VaultError):
    """Raised when AES-256-GCM ciphertext decryption or authentication fails.

    Occurs on authentication tag mismatches, corrupted or truncated payloads (<28 bytes),
    bit flips, or mismatches in Authenticated Additional Data (AAD).
    """

    DEFAULT_ERROR_CODE = "YRV-400-003"


class KeyDerivationError(VaultError):
    """Raised when cryptographic key derivation (e.g. Argon2id) fails."""

    DEFAULT_ERROR_CODE = "YRV-400-004"


__all__ = [
    "DecryptionError",
    "KeyDerivationError",
    "VaultError",
    "VaultLockedError",
]
