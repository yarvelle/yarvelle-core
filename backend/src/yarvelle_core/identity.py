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

"""Neutral application identity.

Core ships no product identity. Every name that ends up on disk, in the OS
keychain, in a cookie, or in a URL scheme is read from environment variables,
with neutral defaults. An application built on core sets these values to keep
its own installs working.

Bootstrap: ``YARVELLE_ENV_PREFIX`` picks the prefix for every other variable
(default ``YARVELLE``). With ``YARVELLE_ENV_PREFIX=ACME`` core reads
``ACME_HOME``, ``ACME_DATABASE_URL``, ``ACME_APP_SLUG`` and so on. A variable
missing under the custom prefix falls back to its ``YARVELLE_`` spelling.

Values are read on every call so tests and embedding apps can change them at
runtime.
"""

from __future__ import annotations

import os
from typing import Optional

BOOTSTRAP_PREFIX = "YARVELLE"
ENV_PREFIX_VAR = "YARVELLE_ENV_PREFIX"

DEFAULT_APP_SLUG = "yarvelle"
DEFAULT_DB_FILENAME = "yarvelle_core.db"
# Exactly 16 bytes. Applications with existing vaults must set their own salt.
DEFAULT_VAULT_SALT = "yarvelle_kek_sal"
VAULT_SALT_LENGTH = 16


def env_prefix() -> str:
    """Returns the active environment variable prefix, without a trailing underscore."""
    raw = (os.getenv(ENV_PREFIX_VAR) or BOOTSTRAP_PREFIX).strip().rstrip("_").upper()
    return raw or BOOTSTRAP_PREFIX


def env_name(suffix: str) -> str:
    """Returns the full environment variable name for a suffix, e.g. ``HOME``."""
    return f"{env_prefix()}_{suffix}"


def getenv(suffix: str, default: Optional[str] = None) -> Optional[str]:
    """Reads ``<PREFIX>_<suffix>``, falling back to ``YARVELLE_<suffix>``, then default.

    Blank values count as unset.
    """
    names = [env_name(suffix)]
    fallback = f"{BOOTSTRAP_PREFIX}_{suffix}"
    if fallback not in names:
        names.append(fallback)
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def app_slug() -> str:
    """Short lowercase application id used to build default names."""
    return (getenv("APP_SLUG") or DEFAULT_APP_SLUG).lower()


def home_dir_name() -> str:
    """Directory name under the user's home that holds runtime data."""
    return getenv("HOME_DIR_NAME") or f".{app_slug()}"


def db_filename() -> str:
    """Relational database file name inside the home directory."""
    return getenv("DB_FILENAME") or DEFAULT_DB_FILENAME


def session_cookie_name() -> str:
    """Name of the browser session cookie."""
    return getenv("SESSION_COOKIE") or f"{app_slug()}_session"


def url_scheme() -> str:
    """Custom URL scheme accepted for companion OAuth relay callbacks."""
    return (getenv("URL_SCHEME") or app_slug()).lower()


def oauth_client_prefix() -> str:
    """Prefix for generated OAuth client ids (``<prefix>-<connector>``)."""
    return getenv("OAUTH_CLIENT_PREFIX") or app_slug()


def keyring_service() -> str:
    """OS keychain service name that stores the vault key."""
    return getenv("KEYRING_SERVICE") or f"{app_slug()}_vault"


def keyring_alt_username() -> str:
    """Secondary keychain entry name checked after ``kek_master``."""
    return getenv("KEYRING_ALT_USERNAME") or f"{app_slug()}_kek"


def local_kek_label() -> str:
    """Label mixed into the dev/test local key derivation."""
    return getenv("LOCAL_KEK_LABEL") or f"{app_slug()}-local-kek"


def local_domain() -> str:
    """Pseudo domain used for local-only identifiers (calendar UIDs, dev users)."""
    return getenv("LOCAL_DOMAIN") or f"{app_slug()}.local"


def vault_salt() -> bytes:
    """Fixed 16-byte vault salt. Changing it makes existing vaults unreadable."""
    raw = (getenv("VAULT_SALT") or DEFAULT_VAULT_SALT).encode("utf-8")
    if len(raw) != VAULT_SALT_LENGTH:
        raise ValueError(
            f"{env_name('VAULT_SALT')} must be exactly {VAULT_SALT_LENGTH} bytes, got {len(raw)}."
        )
    return raw


__all__ = [
    "BOOTSTRAP_PREFIX",
    "DEFAULT_APP_SLUG",
    "DEFAULT_DB_FILENAME",
    "DEFAULT_VAULT_SALT",
    "ENV_PREFIX_VAR",
    "app_slug",
    "db_filename",
    "env_name",
    "env_prefix",
    "getenv",
    "home_dir_name",
    "keyring_alt_username",
    "keyring_service",
    "local_domain",
    "local_kek_label",
    "oauth_client_prefix",
    "session_cookie_name",
    "url_scheme",
    "vault_salt",
]


def pack_packages() -> tuple[str, ...]:
    """Python packages scanned for pack connector starters (``<PREFIX>_PACK_PACKAGES``).

    Comma-separated, empty by default.
    """
    raw = getenv("PACK_PACKAGES") or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


__all__.append("pack_packages")
