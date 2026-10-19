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

"""Domain scope execution context and hierarchical scope validation (Step C2a)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Collection, FrozenSet, Iterator, Optional, Set, Union

DEFAULT_SCOPE = "health"
DEFAULT_HEALTH_GRANTED_SCOPES: FrozenSet[str] = frozenset({"health", "health.*"})


class ScopeError(Exception):
    """Base exception for all domain scoping violations."""

    pass


class ScopeAccessDeniedError(ScopeError):
    """Raised when an action or query targets a scope outside granted permissions."""

    def __init__(
        self,
        required_scope: str,
        granted_scopes: Collection[str],
        message: Optional[str] = None,
    ) -> None:
        msg = message or (
            f"Scope access denied: required '{required_scope}', "
            f"granted scopes: {sorted(list(granted_scopes))}"
        )
        super().__init__(msg)
        self.required_scope = required_scope
        self.granted_scopes = set(granted_scopes)


class ScopeViolationError(ScopeError):
    """Raised when an entity write or flush violates scope ownership invariants."""

    pass


def matches_scope(pattern: str, target: str) -> bool:
    """Evaluates hierarchical scope matching.

    Examples:
        matches_scope('*', 'finance.accounts') -> True
        matches_scope('health.*', 'health.records') -> True
        matches_scope('health.*', 'health') -> True
        matches_scope('health.*', 'finance.accounts') -> False
        matches_scope('health.records', 'health.records') -> True
    """
    if pattern == "*":
        return True
    if pattern == target:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return target == prefix or target.startswith(prefix + ".")
    return False


def is_scope_granted(target_scope: str, granted_scopes: Collection[str]) -> bool:
    """Returns True if target_scope is permitted by any pattern in granted_scopes."""
    return any(matches_scope(pattern, target_scope) for pattern in granted_scopes)


@dataclass(frozen=True)
class ScopeContext:
    """Immutable ambient domain-scope execution context."""

    profile_id: Optional[str] = None
    actor: Optional[str] = None
    pack_id: Optional[str] = None
    scope: str = DEFAULT_SCOPE
    granted_scopes: FrozenSet[str] = field(default_factory=lambda: DEFAULT_HEALTH_GRANTED_SCOPES)
    active_scopes: FrozenSet[str] = field(default_factory=lambda: frozenset({DEFAULT_SCOPE}))
    pack_declared_scopes: FrozenSet[str] = field(
        default_factory=lambda: frozenset({DEFAULT_SCOPE, f"{DEFAULT_SCOPE}.*"})
    )
    declared_reads: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.scope or not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError("ScopeContext requires a non-empty string 'scope'")
        if self.granted_scopes and not is_scope_granted(self.scope, self.granted_scopes):
            raise ScopeAccessDeniedError(self.scope, self.granted_scopes)

    def has_scope(self, scope: str) -> bool:
        """Returns True if the specified scope is permitted by granted_scopes."""
        return is_scope_granted(scope, self.granted_scopes)

    @classmethod
    def get(cls) -> Optional[ScopeContext]:
        """Convenience accessor matching ADR specification."""
        return current_scope_context()


_CURRENT_SCOPE_CONTEXT: ContextVar[Optional[ScopeContext]] = ContextVar(
    "_yarvelle_scope_context", default=None
)


def current_scope_context() -> Optional[ScopeContext]:
    """Returns the currently active ScopeContext, or None if un-set."""
    return _CURRENT_SCOPE_CONTEXT.get()


def current_scope() -> str:
    """Returns the active domain scope string (defaults to 'health' if un-set)."""
    ctx = _CURRENT_SCOPE_CONTEXT.get()
    return ctx.scope if ctx is not None else DEFAULT_SCOPE


def current_granted_scopes() -> Set[str]:
    """Returns the set of active granted scopes (defaults to {'health', 'health.*'})."""
    ctx = _CURRENT_SCOPE_CONTEXT.get()
    if ctx is not None:
        return set(ctx.granted_scopes)
    return set(DEFAULT_HEALTH_GRANTED_SCOPES)


@contextmanager
def scope_context(
    scope: str = DEFAULT_SCOPE,
    granted_scopes: Optional[Collection[str]] = None,
    active_scopes: Optional[Collection[str]] = None,
    profile_id: Optional[str] = None,
    actor: Optional[str] = None,
    pack_id: Optional[str] = None,
    pack_declared_scopes: Optional[Collection[str]] = None,
    declared_reads: Optional[Collection[str]] = None,
) -> Iterator[ScopeContext]:
    """Context manager for setting ambient scope in sync/async blocks."""
    grants = (
        frozenset(granted_scopes)
        if granted_scopes is not None
        else (
            frozenset({scope, f"{scope}.*"})
            if scope != DEFAULT_SCOPE
            else DEFAULT_HEALTH_GRANTED_SCOPES
        )
    )
    actives = frozenset(active_scopes) if active_scopes is not None else frozenset({scope})
    declared = (
        frozenset(pack_declared_scopes)
        if pack_declared_scopes is not None
        else (
            frozenset({scope, f"{scope}.*"})
            if scope != DEFAULT_SCOPE
            else DEFAULT_HEALTH_GRANTED_SCOPES
        )
    )
    reads = frozenset(declared_reads) if declared_reads is not None else frozenset()

    ctx = ScopeContext(
        profile_id=profile_id,
        actor=actor,
        pack_id=pack_id,
        scope=scope,
        granted_scopes=grants,
        active_scopes=actives,
        pack_declared_scopes=declared,
        declared_reads=reads,
    )
    token: Token[Optional[ScopeContext]] = _CURRENT_SCOPE_CONTEXT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_SCOPE_CONTEXT.reset(token)


def require_scope(scope: str, level: str = "read") -> None:
    """Enforces that the current execution context holds the required scope."""
    ctx = _CURRENT_SCOPE_CONTEXT.get()
    granted = set(ctx.granted_scopes) if ctx else set(DEFAULT_HEALTH_GRANTED_SCOPES)
    if not is_scope_granted(scope, granted):
        raise ScopeAccessDeniedError(scope, granted)


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
]
