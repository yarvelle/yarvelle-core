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

"""Scoped session management and SQLAlchemy query/flush interception (Step C2a)."""

from __future__ import annotations

from typing import Any, Optional, Sequence, Set
from sqlalchemy import event, inspect, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from yarvelle_core.scope.context import (
    DEFAULT_SCOPE,
    ScopeViolationError,
    current_granted_scopes,
    current_scope,
    current_scope_context,
    is_scope_granted,
)
from yarvelle_core.scope.mixin import ScopedMixin


def _build_scope_criteria(cls: Any, allowed_scopes: Set[str]) -> Any:
    """Constructs a composite SQLAlchemy expression matching allowed scopes."""
    conditions = []
    exact_scopes = []
    for sc in allowed_scopes:
        if sc == "*":
            return True
        if sc.endswith(".*"):
            prefix = sc[:-2]
            conditions.append(cls.scope == prefix)
            conditions.append(cls.scope.like(f"{prefix}.%"))
        else:
            exact_scopes.append(sc)

    if exact_scopes:
        conditions.append(cls.scope.in_(exact_scopes))

    if not conditions:
        return False
    return or_(*conditions)


def _enforce_do_orm_execute(orm_execute_state: ORMExecuteState) -> None:
    """Intercepts SELECT, UPDATE, and DELETE executions and injects ScopedMixin scope criteria."""
    if not (orm_execute_state.is_select or orm_execute_state.is_update or orm_execute_state.is_delete):
        return

    # Check for explicit bypass option (admin, migrations, cross-domain aggregations)
    if orm_execute_state.execution_options.get("include_all_scopes", False):
        return

    ctx = current_scope_context()
    if ctx is not None:
        allowed_scopes = set(ctx.active_scopes)
        # Also allow reading granted scopes if active is wildcard
        if any(sc.endswith(".*") or sc == "*" for sc in allowed_scopes):
            allowed_scopes.update(ctx.granted_scopes)
    else:
        # Fallback for legacy single-domain usage
        fallback_scope = current_scope()
        allowed_scopes = {fallback_scope, f"{fallback_scope}.*"}

    if "*" in allowed_scopes:
        return

    stmt = orm_execute_state.statement
    if orm_execute_state.is_select:
        for desc in getattr(stmt, "column_descriptions", []):
            cls = desc.get("type")
            if isinstance(cls, type) and issubclass(cls, ScopedMixin):
                orm_execute_state.statement = orm_execute_state.statement.where(
                    _build_scope_criteria(cls, allowed_scopes)
                )
    elif orm_execute_state.is_update or orm_execute_state.is_delete:
        entity = getattr(stmt, "entity_description", None)
        cls = entity.get("type") if entity else None
        if isinstance(cls, type) and issubclass(cls, ScopedMixin):
            orm_execute_state.statement = orm_execute_state.statement.where(
                _build_scope_criteria(cls, allowed_scopes)
            )


def _enforce_before_flush(
    session: Session, flush_context: Any, instances: Optional[Sequence[Any]] = None
) -> None:
    """Guards flush operations to enforce scope write ownership."""
    if session.info.get("skip_scope_guard", False) or session.info.get("include_all_scopes", False):
        return

    ctx = current_scope_context()
    active_scope = current_scope()
    granted_scopes = current_granted_scopes()

    # 1. Inspect new instances
    for instance in session.new:
        if isinstance(instance, ScopedMixin):
            from yarvelle_core.db.models import AuditEventRecord
            if isinstance(instance, AuditEventRecord):
                if not getattr(instance, "scope", None):
                    instance.scope = active_scope
                continue

            inst_scope = getattr(instance, "scope", None)
            if not inst_scope:
                instance.scope = active_scope
            else:
                if not is_scope_granted(instance.scope, granted_scopes):
                    raise ScopeViolationError(
                        f"Cannot create {instance.__class__.__name__} with scope '{instance.scope}': "
                        f"not permitted in active granted scopes {sorted(list(granted_scopes))}"
                    )

    # 2. Inspect modified instances
    for instance in session.dirty:
        if isinstance(instance, ScopedMixin):
            state = inspect(instance)
            history = state.get_history("scope", True)
            if history.has_changes():
                new_scope = getattr(instance, "scope")
                if not is_scope_granted(new_scope, granted_scopes):
                    raise ScopeViolationError(
                        f"Cannot change {instance.__class__.__name__} scope to '{new_scope}': "
                        f"not permitted in active granted scopes {sorted(list(granted_scopes))}"
                    )
            if not is_scope_granted(instance.scope, granted_scopes):
                raise ScopeViolationError(
                    f"Cannot modify {instance.__class__.__name__} with scope '{instance.scope}': "
                    f"not permitted in active granted scopes {sorted(list(granted_scopes))}"
                )

    # 3. Inspect deleted instances
    for instance in session.deleted:
        if isinstance(instance, ScopedMixin):
            if not is_scope_granted(instance.scope, granted_scopes):
                raise ScopeViolationError(
                    f"Cannot delete {instance.__class__.__name__} with scope '{instance.scope}': "
                    f"not permitted in active granted scopes {sorted(list(granted_scopes))}"
                )


class ScopedAsyncSession(AsyncSession):
    """AsyncSession subclass with convenience methods for scoped operations."""

    def with_scope(self, scope: str) -> ScopedAsyncSession:
        """Configures the session to execute within a specific scope."""
        self.info["scope"] = scope
        return self

    def include_all_scopes(self) -> ScopedAsyncSession:
        """Exempts subsequent executions in this session from scope filtering."""
        self.info["include_all_scopes"] = True
        return self


_LISTENERS_REGISTERED = False


def register_scope_listeners(target_session_class: Any = Session) -> None:
    """Attaches do_orm_execute and before_flush event listeners once."""
    global _LISTENERS_REGISTERED
    if not _LISTENERS_REGISTERED:
        event.listen(target_session_class, "do_orm_execute", _enforce_do_orm_execute)
        event.listen(target_session_class, "before_flush", _enforce_before_flush)
        _LISTENERS_REGISTERED = True


# Automatically register on the base Session class upon import
register_scope_listeners()


__all__ = [
    "ScopedAsyncSession",
    "register_scope_listeners",
]
