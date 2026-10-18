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

"""Cryptographic salt and keyring service pinning test."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from yarvelle_core.vault import kek
from yarvelle_core.vault.kek import (
    DEFAULT_ARGON2_SALT,
    derive_argon2id_kek,
    resolve_kek,
)


def test_argon2_salt_literal_pinned():
    """Verify DEFAULT_ARGON2_SALT is exactly b'carefold_kek_sal' and 16 bytes."""
    assert DEFAULT_ARGON2_SALT == b"carefold_kek_sal", (
        "CRITICAL: DEFAULT_ARGON2_SALT has changed! Modifying this constant will "
        "render existing user vaults permanently un-decryptable."
    )
    assert len(DEFAULT_ARGON2_SALT) == 16, "Argon2 salt must be exactly 16 bytes."


def test_argon2id_derivation_deterministic():
    """Verify Argon2id KEK derivation matches the pinned golden derived key."""
    test_passphrase = "carefold_master_test_passphrase"
    derived = derive_argon2id_kek(test_passphrase, DEFAULT_ARGON2_SALT)
    assert len(derived) == 32, "Derived KEK must be exactly 32 bytes (256 bits)."

    expected_hex = "5336658ab69d6275883d815b7a0d122842bb0052a8bb24ad8098e7e8c370a718"
    assert derived.hex() == expected_hex, (
        "Argon2id derivation output drifted! Argon2 parameters or salt have changed."
    )


def test_keyring_service_name_pinned():
    """Verify resolve_kek queries OS keyring under the service name 'carefold_vault'."""
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "a" * 64

    with patch.object(kek, "HAS_KEYRING", True), patch.object(kek, "keyring", mock_keyring):
        resolved = resolve_kek(mode="local")
        assert resolved == bytes.fromhex("a" * 64)
        mock_keyring.get_password.assert_any_call("carefold_vault", "kek_master")


def test_keyring_service_literal_in_source():
    """AST check: ensure 'carefold_vault' literal exists in vault/kek.py."""
    kek_source_path = Path(kek.__file__).resolve()
    tree = ast.parse(kek_source_path.read_text(encoding="utf-8"))

    found_service = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "carefold_vault":
            found_service = True
            break

    assert found_service, (
        "Literal 'carefold_vault' not found in vault/kek.py AST! Keyring service name must remain pinned."
    )
