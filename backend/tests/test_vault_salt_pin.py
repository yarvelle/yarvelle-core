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


"""Vault salt and keychain names: neutral defaults, compatible overrides.

The salt and keychain service name come from ``yarvelle_core.identity``. An
application with existing vaults sets the values it was created with; the key
derivation itself must never change.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from yarvelle_core import identity
from yarvelle_core.vault import kek
from yarvelle_core.vault.dek import derive_scope_dek
from yarvelle_core.vault.kek import derive_argon2id_kek, resolve_kek

# A downstream application's salt from before core was neutral. Its golden
# derived key below proves the derivation is unchanged when the app sets it.
LEGACY_APP_SALT = "carefold_kek_sal"
LEGACY_GOLDEN_HEX = "5336658ab69d6275883d815b7a0d122842bb0052a8bb24ad8098e7e8c370a718"
TEST_PASSPHRASE = "carefold_master_test_passphrase"


@pytest.fixture(autouse=True)
def _clean_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for suffix in ("VAULT_SALT", "KEYRING_SERVICE", "KEYRING_ALT_USERNAME", "APP_SLUG"):
        monkeypatch.delenv(f"YARVELLE_{suffix}", raising=False)
    monkeypatch.delenv("YARVELLE_ENV_PREFIX", raising=False)


def test_default_salt_is_neutral_and_16_bytes() -> None:
    assert identity.vault_salt() == b"yarvelle_kek_sal"
    assert len(identity.vault_salt()) == 16


def test_salt_must_be_16_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_VAULT_SALT", "short")
    with pytest.raises(ValueError):
        identity.vault_salt()


def test_configured_salt_reproduces_legacy_golden_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_VAULT_SALT", LEGACY_APP_SALT)
    derived = derive_argon2id_kek(TEST_PASSPHRASE)
    assert derived.hex() == LEGACY_GOLDEN_HEX
    # Explicit salt argument still wins and gives the same key.
    assert derive_argon2id_kek(TEST_PASSPHRASE, LEGACY_APP_SALT.encode()).hex() == LEGACY_GOLDEN_HEX


def test_salt_via_custom_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_ENV_PREFIX", "ACME")
    monkeypatch.setenv("ACME_VAULT_SALT", LEGACY_APP_SALT)
    assert derive_argon2id_kek(TEST_PASSPHRASE).hex() == LEGACY_GOLDEN_HEX


def test_default_salt_gives_different_key() -> None:
    assert derive_argon2id_kek(TEST_PASSPHRASE).hex() != LEGACY_GOLDEN_HEX


def test_scope_dek_uses_configured_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_dek = bytes(range(32))
    neutral = derive_scope_dek(profile_dek, "finance")
    monkeypatch.setenv("YARVELLE_VAULT_SALT", LEGACY_APP_SALT)
    legacy = derive_scope_dek(profile_dek, "finance")
    assert neutral != legacy
    assert len(legacy) == 32


def test_keyring_service_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = "a" * 64
    with patch.object(kek, "HAS_KEYRING", True), patch.object(kek, "keyring", mock_keyring):
        assert resolve_kek(mode="local") == bytes.fromhex("a" * 64)
        mock_keyring.get_password.assert_any_call("yarvelle_vault", "kek_master")

        mock_keyring.reset_mock()
        monkeypatch.setenv("YARVELLE_KEYRING_SERVICE", "legacy_vault")
        resolve_kek(mode="local")
        mock_keyring.get_password.assert_any_call("legacy_vault", "kek_master")


def test_keyring_alt_username_override(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_keyring = MagicMock()
    mock_keyring.get_password.side_effect = lambda service, user: "b" * 64 if user == "legacy_kek" else None
    monkeypatch.setenv("YARVELLE_KEYRING_SERVICE", "legacy_vault")
    monkeypatch.setenv("YARVELLE_KEYRING_ALT_USERNAME", "legacy_kek")
    with patch.object(kek, "HAS_KEYRING", True), patch.object(kek, "keyring", mock_keyring):
        assert resolve_kek(mode="local") == bytes.fromhex("b" * 64)
        mock_keyring.get_password.assert_any_call("legacy_vault", "legacy_kek")
