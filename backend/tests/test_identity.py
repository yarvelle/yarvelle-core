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


"""Neutral application identity settings."""

from __future__ import annotations

import pytest

from yarvelle_core import identity
from yarvelle_core.connectors.relay import validate_relay_callback_target

_SUFFIXES = (
    "APP_SLUG", "HOME_DIR_NAME", "DB_FILENAME", "SESSION_COOKIE", "URL_SCHEME",
    "OAUTH_CLIENT_PREFIX", "KEYRING_SERVICE", "KEYRING_ALT_USERNAME", "LOCAL_KEK_LABEL",
    "LOCAL_DOMAIN", "VAULT_SALT", "PACK_PACKAGES",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YARVELLE_ENV_PREFIX", raising=False)
    for suffix in _SUFFIXES:
        monkeypatch.delenv(f"YARVELLE_{suffix}", raising=False)
        monkeypatch.delenv(f"ACME_{suffix}", raising=False)


def test_neutral_defaults() -> None:
    assert identity.env_prefix() == "YARVELLE"
    assert identity.env_name("HOME") == "YARVELLE_HOME"
    assert identity.app_slug() == "yarvelle"
    assert identity.home_dir_name() == ".yarvelle"
    assert identity.db_filename() == "yarvelle_core.db"
    assert identity.session_cookie_name() == "yarvelle_session"
    assert identity.url_scheme() == "yarvelle"
    assert identity.oauth_client_prefix() == "yarvelle"
    assert identity.keyring_service() == "yarvelle_vault"
    assert identity.keyring_alt_username() == "yarvelle_kek"
    assert identity.local_kek_label() == "yarvelle-local-kek"
    assert identity.local_domain() == "yarvelle.local"
    assert identity.pack_packages() == ()


def test_slug_drives_derived_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_APP_SLUG", "acme")
    assert identity.home_dir_name() == ".acme"
    assert identity.session_cookie_name() == "acme_session"
    assert identity.url_scheme() == "acme"
    assert identity.keyring_service() == "acme_vault"
    assert identity.keyring_alt_username() == "acme_kek"
    # The database file name and salt are never derived from the slug.
    assert identity.db_filename() == "yarvelle_core.db"
    assert identity.vault_salt() == b"yarvelle_kek_sal"


def test_custom_prefix_with_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_ENV_PREFIX", "acme_")
    monkeypatch.setenv("ACME_APP_SLUG", "acme")
    monkeypatch.setenv("YARVELLE_DB_FILENAME", "shared.db")
    assert identity.env_prefix() == "ACME"
    assert identity.env_name("HOME") == "ACME_HOME"
    assert identity.app_slug() == "acme"
    assert identity.db_filename() == "shared.db"


def test_blank_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_APP_SLUG", "   ")
    assert identity.app_slug() == "yarvelle"


def test_pack_packages_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARVELLE_PACK_PACKAGES", " acme, acme_finance ,,")
    assert identity.pack_packages() == ("acme", "acme_finance")


def test_relay_accepts_configured_scheme_only(monkeypatch: pytest.MonkeyPatch) -> None:
    assert validate_relay_callback_target("yarvelle://oauth/done") == "yarvelle://oauth/done"
    with pytest.raises(ValueError):
        validate_relay_callback_target("acme://oauth/done")
    monkeypatch.setenv("YARVELLE_URL_SCHEME", "acme")
    assert validate_relay_callback_target("acme://oauth/done") == "acme://oauth/done"
    with pytest.raises(ValueError):
        validate_relay_callback_target("yarvelle://oauth/done")


def test_home_dir_and_db_name_follow_identity(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from yarvelle_core.config import BrandConfig, resolve_yarvelle_home

    monkeypatch.delenv("YARVELLE_HOME", raising=False)
    monkeypatch.delenv("YARVELLE_HOME_DIR", raising=False)
    monkeypatch.delenv("YARVELLE_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("YARVELLE_APP_SLUG", "acme")
    monkeypatch.setenv("YARVELLE_DB_FILENAME", "acme.db")
    assert resolve_yarvelle_home() == (tmp_path / ".acme").resolve()
    brand = BrandConfig()
    assert brand.home_dir_name == ".acme"
    assert brand.db_filename == "acme.db"
    assert brand.oauth_scheme == "acme"
