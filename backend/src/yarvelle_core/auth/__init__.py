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

"""Authentication subsystem providing hexagonal AuthPort and swappable adapters."""

from yarvelle_core.auth.adapters.disabled_adapter import (
    DEFAULT_STEWARD_USER,
    DisabledAuthAdapter,
)
from yarvelle_core.auth.adapters.oidc_adapter import OidcAuthAdapter
from yarvelle_core.auth.adapters.sql_adapter import SqlAuthAdapter
from yarvelle_core.auth.factory import (
    create_auth_port,
    get_auth_port,
    reset_auth_port,
    reset_auth_ports,
    set_auth_port,
)
from yarvelle_core.auth.ports import (
    AuthPort,
    AuthSession,
    PaginatedUsers,
    PasswordChangeRequest,
    PasswordResetRequest,
    RegisterUserRequest,
    SessionRecord,
    SessionToken,
    UserProfile,
    UserRecord,
    UserUpdate,
    ValidatedSession,
)

__all__ = [
    "AuthPort",
    "AuthSession",
    "DEFAULT_STEWARD_USER",
    "DisabledAuthAdapter",
    "OidcAuthAdapter",
    "PaginatedUsers",
    "PasswordChangeRequest",
    "PasswordResetRequest",
    "RegisterUserRequest",
    "SessionRecord",
    "SessionToken",
    "SqlAuthAdapter",
    "UserProfile",
    "UserRecord",
    "UserUpdate",
    "ValidatedSession",
    "create_auth_port",
    "get_auth_port",
    "reset_auth_port",
    "reset_auth_ports",
    "set_auth_port",
]
