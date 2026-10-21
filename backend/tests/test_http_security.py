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

"""CORS options and unauthenticated non-loopback bind guard."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from yarvelle_core.api.http_security import (
    CorsConfigError,
    InsecureBindError,
    build_cors_options,
    enforce_bind_safety,
    is_loopback_host,
    normalize_cors_origins,
)
from yarvelle_core.constants.defaults import DEFAULT_CORS_ORIGINS

OVERRIDE = "YARVELLE_TEST_ALLOW_INSECURE_BIND"


@pytest.mark.parametrize("bad", ["*", "https://*.example.test", "null", "ftp://x.test", "http://x.test/path", "http://u:p@x.test"])
def test_unsafe_or_malformed_origins_are_rejected(bad: str) -> None:
    with pytest.raises(CorsConfigError):
        normalize_cors_origins([bad])


def test_origins_are_normalized_and_default_to_localhost() -> None:
    assert normalize_cors_origins("http://LOCALHOST:3000/, https://app.example.test") == [
        "http://localhost:3000",
        "https://app.example.test",
    ]
    assert normalize_cors_origins([]) == list(DEFAULT_CORS_ORIGINS)
    assert normalize_cors_origins(None) == list(DEFAULT_CORS_ORIGINS)


def test_cors_options_are_explicit_and_enforced() -> None:
    options = build_cors_options(["http://localhost:3000"])
    assert "*" not in options["allow_methods"] and "*" not in options["allow_headers"]
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **options)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    client = TestClient(app)
    allowed = client.get("/ping", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = client.get("/ping", headers={"Origin": "http://evil.example.test"})
    assert "access-control-allow-origin" not in denied.headers
    preflight = client.options(
        "/ping",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Not-Allowed",
        },
    )
    assert preflight.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1", "[::1]"])
def test_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.test", ""])
def test_non_loopback_hosts(host: str) -> None:
    assert not is_loopback_host(host)


def test_bind_guard_refuses_unauthenticated_network_bind(monkeypatch) -> None:
    monkeypatch.delenv(OVERRIDE, raising=False)
    with pytest.raises(InsecureBindError):
        enforce_bind_safety("0.0.0.0", "disabled", override_env=OVERRIDE)
    enforce_bind_safety("127.0.0.1", "disabled", override_env=OVERRIDE)
    enforce_bind_safety("0.0.0.0", "local", override_env=OVERRIDE)


def test_bind_guard_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv(OVERRIDE, "0")
    with pytest.raises(InsecureBindError):
        enforce_bind_safety("0.0.0.0", "disabled", override_env=OVERRIDE)
    monkeypatch.setenv(OVERRIDE, "1")
    enforce_bind_safety("0.0.0.0", "disabled", override_env=OVERRIDE)
