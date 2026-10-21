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

"""HTTP exposure guards shared by Yarvelle Core applications.

- ``build_cors_options``: explicit origins, methods and headers for
  ``CORSMiddleware``; a wildcard origin is never combined with credentials.
- ``enforce_bind_safety``: refuses to start when authentication is disabled
  and the server binds a non-loopback interface, unless the operator sets an
  explicit override.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit

from yarvelle_core.constants.defaults import DEFAULT_CORS_ORIGINS
from yarvelle_core.logging import get_logger

logger = get_logger("yarvelle_core.api.http_security")

DEFAULT_CORS_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
DEFAULT_CORS_HEADERS: tuple[str, ...] = (
    "Accept",
    "Accept-Language",
    "Authorization",
    "Cache-Control",
    "Content-Type",
    "Last-Event-ID",
    "X-API-Key",
    "X-Domain-Scopes",
    "X-Model",
    "X-Provider",
    "X-Requested-With",
)
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class CorsConfigError(ValueError):
    """Raised for CORS origins that cannot be safely combined with credentials."""


class InsecureBindError(RuntimeError):
    """Raised when auth is disabled on a non-loopback bind without an explicit override."""


def normalize_cors_origins(origins: str | Iterable[str] | None) -> list[str]:
    """Validates and normalizes configured CORS origins.

    Accepts a comma-separated string or an iterable. Each origin must be an
    ``http``/``https`` scheme plus host (and optional port) with no path.
    ``*`` and ``null`` are rejected because the API uses credentialed
    requests. An empty configuration falls back to the localhost defaults.
    """
    if origins is None:
        raw: list[str] = []
    elif isinstance(origins, str):
        raw = origins.split(",")
    else:
        raw = [str(o) for o in origins]

    result: list[str] = []
    for item in raw:
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin in ("*", "null") or "*" in origin:
            raise CorsConfigError(
                f"CORS origin '{origin}' is not allowed with credentialed requests; list explicit origins."
            )
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment:
            raise CorsConfigError(f"Invalid CORS origin '{origin}': expected scheme://host[:port].")
        if parts.username or parts.password:
            raise CorsConfigError(f"Invalid CORS origin '{origin}': credentials are not allowed.")
        normalized = f"{parts.scheme}://{parts.netloc.lower()}"
        if normalized not in result:
            result.append(normalized)
    return result or list(DEFAULT_CORS_ORIGINS)


def build_cors_options(
    origins: str | Iterable[str] | None,
    *,
    extra_headers: Sequence[str] = (),
    allow_credentials: bool = True,
) -> dict[str, Any]:
    """Keyword arguments for ``app.add_middleware(CORSMiddleware, **options)``."""
    headers = list(dict.fromkeys([*DEFAULT_CORS_HEADERS, *extra_headers]))
    return {
        "allow_origins": normalize_cors_origins(origins),
        "allow_credentials": allow_credentials,
        "allow_methods": list(DEFAULT_CORS_METHODS),
        "allow_headers": headers,
        "max_age": 600,
    }


def is_loopback_host(host: str | None) -> bool:
    """True for localhost names and loopback IPv4/IPv6 addresses."""
    clean = (host or "").strip().lower().strip("[]")
    if not clean:
        return False
    if clean == "localhost" or clean.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def env_flag(name: str) -> bool:
    """True when the environment variable is set to a truthy value."""
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def enforce_bind_safety(
    host: str | None,
    auth_provider: str | None,
    *,
    override_env: str,
    product: str = "Yarvelle",
) -> None:
    """Refuses unauthenticated startup on a non-loopback interface.

    With authentication disabled every request acts as the local steward, so
    binding beyond loopback would expose all data to the network. Startup
    is refused unless ``override_env`` is set to a truthy value, in which
    case a warning is logged.
    """
    clean_auth = (auth_provider or "local").strip().lower()
    if clean_auth != "disabled" or is_loopback_host(host):
        return
    if env_flag(override_env):
        logger.warning(
            "security_override_non_loopback_unauthenticated",
            host=host,
            override_env=override_env,
            message=f"{product} is serving without authentication on a non-loopback interface (explicit override).",
        )
        return
    raise InsecureBindError(
        f"Refusing to start {product}: authentication is disabled and the server binds '{host}', "
        f"which is not a loopback address. Enable authentication, bind to 127.0.0.1, or set "
        f"{override_env}=1 to accept the risk explicitly."
    )


__all__ = [
    "DEFAULT_CORS_HEADERS",
    "DEFAULT_CORS_METHODS",
    "CorsConfigError",
    "InsecureBindError",
    "build_cors_options",
    "enforce_bind_safety",
    "env_flag",
    "is_loopback_host",
    "normalize_cors_origins",
]
