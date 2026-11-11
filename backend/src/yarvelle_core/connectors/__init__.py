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
    ConnectorNotConfiguredError,
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
    "ConnectorNotConfiguredError",
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
