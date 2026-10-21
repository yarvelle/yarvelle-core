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

"""Request-time scope enforcement for pack router contributions (02 §3, §4.2).

Every router a pack contributes is mounted behind ``require_pack_scope``, which
authenticates the caller, resolves the target profile from the path or query
and checks that the caller owns or manages the profile, or holds an unexpired
ScopeGrant that covers the router's scope at the required level. Mutating
methods always need at least ``write``. Pack code never has to remember to
add auth itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, List, Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.deps import get_current_user, get_user_profile_access
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Profile, ScopeGrant
from yarvelle_core.db.session import get_db
from yarvelle_core.scope.context import matches_scope

SCOPE_LEVEL_RANK = {"read": 1, "write": 2, "approve": 3}
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SCOPE_GUARD_MARKER = "__yarvelle_scope_guard__"


@dataclass(frozen=True)
class PackScopeGrant:
    """Authorization outcome attached to request.state.pack_scope."""

    scope: str
    level: str
    profile_id: Optional[str]
    user_id: str
    pack_id: Optional[str]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def has_scope_access(
    db: AsyncSession,
    profile: Profile,
    user: UserProfile,
    scope: str,
    level: str,
) -> bool:
    """True when user may act on scope at level for profile.

    Owners and holders of the profile-level ``manage`` grant pass. Anyone else
    needs an unexpired ScopeGrant whose pattern matches scope at an equal or
    higher level; profile-wide (user_id NULL) grants only apply to users who
    already hold some access to the profile.
    """
    access = await get_user_profile_access(profile, user, db)
    if access == "manage":
        return True

    required_rank = SCOPE_LEVEL_RANK[level]
    stmt = select(ScopeGrant).where(
        ScopeGrant.profile_id == profile.id,
        or_(ScopeGrant.user_id == user.id, ScopeGrant.user_id.is_(None)),
    )
    now = datetime.now(timezone.utc)
    for grant in (await db.execute(stmt)).scalars().all():
        if grant.user_id is None and access is None:
            continue
        expires_at = _as_utc(grant.expires_at)
        if expires_at is not None and expires_at <= now:
            continue
        if SCOPE_LEVEL_RANK.get(grant.access_level, 0) < required_rank:
            continue
        if matches_scope(grant.scope, scope):
            return True
    return False


def require_pack_scope(
    scope: str,
    level: str = "read",
    *,
    pack_id: Optional[str] = None,
    require_profile: bool = True,
) -> Callable[..., Any]:
    """Builds the FastAPI dependency enforcing scope at level for a pack router."""
    if level not in SCOPE_LEVEL_RANK:
        raise ValueError(f"Unknown scope level '{level}'; expected one of {sorted(SCOPE_LEVEL_RANK)}")
    if not scope or not scope.strip():
        raise ValueError("Pack router scope must be a non-empty scope id")

    async def _guard(
        request: Request,
        user: UserProfile = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> PackScopeGrant:
        required = level
        if request.method.upper() in MUTATING_METHODS and SCOPE_LEVEL_RANK[required] < SCOPE_LEVEL_RANK["write"]:
            required = "write"

        profile_id = request.path_params.get("profile_id") or request.query_params.get("profile_id")
        if not profile_id:
            if require_profile:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="profile_id is required for this scoped route",
                )
        else:
            profile = await db.get(Profile, profile_id)
            if profile is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
            if not await has_scope_access(db, profile, user, scope, required):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access to scope '{scope}' ({required}) denied for this profile",
                )

        grant = PackScopeGrant(
            scope=scope, level=required, profile_id=profile_id, user_id=user.id, pack_id=pack_id
        )
        request.state.pack_scope = grant
        return grant

    setattr(_guard, SCOPE_GUARD_MARKER, (scope, level, pack_id))
    return _guard


def route_scope_guards(route: Any) -> List[Tuple[str, str, Optional[str]]]:
    """Returns (scope, level, pack_id) for every scope guard on route.

    route is anything exposing a FastAPI ``dependant`` (APIRoute, or the
    effective route context newer FastAPI builds for included routers).
    """
    found: List[Tuple[str, str, Optional[str]]] = []
    dependant = getattr(route, "dependant", None)
    stack = list(dependant.dependencies) if dependant is not None else []
    while stack:
        dep = stack.pop()
        marker = getattr(dep.call, SCOPE_GUARD_MARKER, None)
        if marker is not None:
            found.append(marker)
        stack.extend(dep.dependencies)
    return found


def iter_api_routes(routes: Any) -> Iterator[Any]:
    """Yields every effective API route (with ``path``, ``methods``, ``dependant``).

    Flattens included routers, whose dependencies FastAPI >= 0.150 only merges
    into lazily built effective route contexts.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        effective = getattr(route, "effective_route_contexts", None)
        if callable(effective):
            for ctx in effective():
                if getattr(ctx, "dependant", None) is not None:
                    yield ctx


__all__ = [
    "MUTATING_METHODS",
    "PackScopeGrant",
    "SCOPE_LEVEL_RANK",
    "has_scope_access",
    "iter_api_routes",
    "require_pack_scope",
    "route_scope_guards",
]
