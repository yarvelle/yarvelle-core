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

"""Domain scoping and isolation package."""

from __future__ import annotations

from yarvelle_core.scope.context import (
    DEFAULT_HEALTH_GRANTED_SCOPES,
    DEFAULT_SCOPE,
    ScopeAccessDeniedError,
    ScopeContext,
    ScopeError,
    ScopeViolationError,
    current_granted_scopes,
    current_scope,
    current_scope_context,
    is_scope_granted,
    matches_scope,
    require_scope,
    scope_context,
)
from yarvelle_core.scope.adapter import DualWriteAdapter
from yarvelle_core.scope.mixin import ScopedMixin

__all__ = [
    "DEFAULT_SCOPE",
    "DEFAULT_HEALTH_GRANTED_SCOPES",
    "ScopeError",
    "ScopeAccessDeniedError",
    "ScopeViolationError",
    "matches_scope",
    "is_scope_granted",
    "ScopeContext",
    "current_scope_context",
    "current_scope",
    "current_granted_scopes",
    "scope_context",
    "require_scope",
    "ScopedMixin",
    "DualWriteAdapter",
]
