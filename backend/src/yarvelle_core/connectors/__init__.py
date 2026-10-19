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

"""Yarvelle Core Connectors Package (Connector SDK + OAuth Broker, Lifecycle, Consent & Sync Engine)."""

from __future__ import annotations

import sys as _sys

# Register 'connectors' top-level alias pointing to yarvelle_core.connectors
_sys.modules.setdefault("connectors", _sys.modules[__name__])

from yarvelle_core.connectors import base as _base
from yarvelle_core.connectors import errors as _errors
from yarvelle_core.connectors import http as _http
from yarvelle_core.connectors import manifest as _manifest
from yarvelle_core.connectors import starters as _starters
from yarvelle_core.connectors import loader as _loader

_sys.modules.setdefault("connectors.base", _base)
_sys.modules.setdefault("connectors.errors", _errors)
_sys.modules.setdefault("connectors.http", _http)
_sys.modules.setdefault("connectors.manifest", _manifest)
_sys.modules.setdefault("connectors.starters", _starters)
_sys.modules.setdefault("connectors.loader", _loader)

from yarvelle_core.connectors.base import (
    Connector,
    NormalisedRecord,
    Page,
    StreamSpec,
    ToolContext,
    ToolSpec,
)
from yarvelle_core.connectors.errors import (
    AuthExpiredError,
    ConnectorError,
    EgressBlockedError,
    ManifestValidationError,
)
from yarvelle_core.connectors.http import ScopedHttp
from yarvelle_core.connectors.loader import (
    ConnectorRegistry,
    get_connector_registry,
    list_starter_manifests,
    load_connector,
)
from yarvelle_core.connectors.manifest import (
    AuthConfig,
    ConnectorManifest,
    DataFlowSpec,
    McpToolAllowlistEntry,
    PolicyConfig,
    TermsConfig,
    ToolDeclaration,
    TrustConfig,
)
from yarvelle_core.connectors.lifecycle import (
    check_scope_and_terms_compatibility,
    check_under_13_connection_guard,
    get_connector_manifest,
    get_profile_data_flows,
    grant_connector_consent,
    list_connector_manifests,
    record_sync_failure,
    revoke_connection,
    serialize_connector_manifest,
)
from yarvelle_core.connectors.oauth import (
    build_authorization_url,
    create_oauth_state,
    generate_pkce_pair,
    load_connection_tokens,
    refresh_connection_token,
    resolve_redirect_uri,
    store_connection_tokens,
    verify_oauth_state,
    verify_pkce_challenge,
)
from yarvelle_core.connectors.sync import run_connection_sync

__all__ = [
    "AuthConfig",
    "AuthExpiredError",
    "Connector",
    "ConnectorError",
    "ConnectorManifest",
    "ConnectorRegistry",
    "DataFlowSpec",
    "EgressBlockedError",
    "ManifestValidationError",
    "McpToolAllowlistEntry",
    "NormalisedRecord",
    "Page",
    "PolicyConfig",
    "ScopedHttp",
    "StreamSpec",
    "TermsConfig",
    "ToolContext",
    "ToolDeclaration",
    "ToolSpec",
    "TrustConfig",
    "build_authorization_url",
    "check_scope_and_terms_compatibility",
    "check_under_13_connection_guard",
    "create_oauth_state",
    "generate_pkce_pair",
    "get_connector_manifest",
    "get_connector_registry",
    "get_profile_data_flows",
    "grant_connector_consent",
    "list_connector_manifests",
    "list_starter_manifests",
    "load_connection_tokens",
    "load_connector",
    "record_sync_failure",
    "refresh_connection_token",
    "resolve_redirect_uri",
    "revoke_connection",
    "run_connection_sync",
    "serialize_connector_manifest",
    "store_connection_tokens",
    "verify_oauth_state",
    "verify_pkce_challenge",
]
