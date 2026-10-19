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

"""REST API endpoints for current user UI context and profile UI preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.deps import get_current_user, resolve_owner_user_id
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.config import settings
from yarvelle_core.db.models import Profile, ProfileAccess, ProfileUiPreference, ScopeGrant, utc_now
from yarvelle_core.db.session import get_db
from yarvelle_core.schemas.profiles import (
    AudienceBand,
    ProfileUiContextResponse,
    ProfileUiPreferenceResponse,
    ProfileUiPreferenceUpdate,
)
from yarvelle_core.scope.context import DEFAULT_HEALTH_GRANTED_SCOPES

router = APIRouter()


def _compute_audience(profile: Profile) -> AudienceBand:
    """Computes audience classification band based on age and profile role."""
    if profile.role == "viewer":
        return "viewer"

    if profile.date_of_birth:
        try:
            dob = datetime.strptime(profile.date_of_birth.strip(), "%Y-%m-%d").date()
            today = datetime.now(timezone.utc).date()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if age < 13:
                return "child"
            if age < 18:
                return "teen"
            return "adult"
        except (ValueError, TypeError):
            pass

    return "adult"


def _is_admin_or_steward(user: UserProfile) -> bool:
    """Returns True if user is an administrator or system steward."""
    return (
        getattr(user, "role", None) == "admin"
        or getattr(user, "username", None) == "steward"
        or getattr(user, "id", None) == DEFAULT_STEWARD_USER.id
        or getattr(user, "id", None) == "steward"
    )


async def _resolve_target_profile(
    profile_id: Optional[str],
    current_user: UserProfile,
    db: AsyncSession,
) -> Profile:
    """Resolves and validates access to the target profile."""
    is_admin = _is_admin_or_steward(current_user)
    owner_id = resolve_owner_user_id(current_user)
    effective_user_id = owner_id or current_user.id

    if profile_id:
        res = await db.execute(select(Profile).where(Profile.id == profile_id))
        profile = res.scalar_one_or_none()
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile '{profile_id}' not found",
            )
        # Validate authorization if user is not steward/admin
        if not is_admin:
            is_owner = (profile.user_id == effective_user_id) or (owner_id is None and profile.user_id is None)
            if not is_owner:
                access_res = await db.execute(
                    select(ProfileAccess).where(
                        ProfileAccess.profile_id == profile_id,
                        ProfileAccess.user_id == effective_user_id,
                    )
                )
                if access_res.scalar_one_or_none() is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access to profile denied",
                    )
        return profile

    # Default profile resolution when profile_id is not specified
    stmt = select(Profile)
    if not is_admin:
        if owner_id:
            stmt = stmt.where(Profile.user_id == owner_id)
        elif effective_user_id:
            stmt = stmt.where(Profile.user_id == effective_user_id)
        else:
            stmt = stmt.where(Profile.user_id.is_(None))
    stmt = stmt.order_by(Profile.is_primary.desc(), Profile.role == "self", Profile.id)
    res = await db.execute(stmt)
    profile = res.scalars().first()

    if profile is None and not is_admin:
        # Check shared profiles where user has access
        shared_res = await db.execute(
            select(Profile)
            .join(ProfileAccess, Profile.id == ProfileAccess.profile_id)
            .where(ProfileAccess.user_id == effective_user_id)
            .order_by(Profile.id)
        )
        profile = shared_res.scalars().first()

    if profile is None and (is_admin or (owner_id is None and getattr(settings, "auth_provider", "local") == "disabled")):
        # Fallback to any profile in single-user/local environment or admin
        any_res = await db.execute(select(Profile).order_by(Profile.id))
        profile = any_res.scalars().first()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile found for current user",
        )
    return profile


@router.get(
    "/ui-context",
    response_model=ProfileUiContextResponse,
    summary="Get active UI context and preferences for profile",
)
async def get_ui_context(
    profile_id: Optional[str] = Query(default=None, description="Target profile UUID"),
    x_profile_id: Optional[str] = Header(
        default=None,
        alias="X-Profile-ID",
        description="Target profile UUID passed via header",
    ),
    current_user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUiContextResponse:
    """Returns active scopes, hidden panels, and audience classification for the active profile."""
    target_id = profile_id or x_profile_id
    profile = await _resolve_target_profile(target_id, current_user, db)

    # 1. Resolve granted scopes for this profile
    scopes: List[str] = []
    grant_stmt = select(ScopeGrant).where(ScopeGrant.profile_id == profile.id)
    if not _is_admin_or_steward(current_user):
        grant_stmt = grant_stmt.where(
            (ScopeGrant.user_id == current_user.id) | (ScopeGrant.user_id.is_(None))
        )
    grants_res = await db.execute(grant_stmt)
    grants = grants_res.scalars().all()

    if grants:
        scopes = sorted(list({g.scope for g in grants}))
    else:
        # Default fallback scopes
        scopes = sorted(list(DEFAULT_HEALTH_GRANTED_SCOPES))

    # 2. Resolve UI preferences (hidden panels)
    pref_res = await db.execute(
        select(ProfileUiPreference).where(ProfileUiPreference.profile_id == profile.id)
    )
    pref = pref_res.scalar_one_or_none()
    hidden_panels = pref.hidden_panels if pref and pref.hidden_panels else []

    # 3. Compute audience band
    audience = _compute_audience(profile)

    return ProfileUiContextResponse(
        profile_id=profile.id,
        scopes=scopes,
        hidden_panels=hidden_panels,
        audience=audience,
    )


@router.get(
    "/profiles/{profile_id}/ui-prefs",
    response_model=ProfileUiPreferenceResponse,
    summary="Get UI preferences for a specific profile",
)
async def get_profile_ui_prefs(
    profile_id: str,
    current_user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUiPreferenceResponse:
    """Retrieves layout customizations and hidden panel preferences for a profile."""
    profile = await _resolve_target_profile(profile_id, current_user, db)

    pref_res = await db.execute(
        select(ProfileUiPreference).where(ProfileUiPreference.profile_id == profile.id)
    )
    pref = pref_res.scalar_one_or_none()

    if pref is None:
        return ProfileUiPreferenceResponse(
            profile_id=profile.id,
            hidden_panels=[],
            theme_preference=None,
        )

    return ProfileUiPreferenceResponse(
        profile_id=profile.id,
        hidden_panels=pref.hidden_panels or [],
        theme_preference=pref.theme_preference,
    )


@router.put(
    "/profiles/{profile_id}/ui-prefs",
    response_model=ProfileUiPreferenceResponse,
    summary="Update UI preferences for a specific profile",
)
async def update_profile_ui_prefs(
    profile_id: str,
    body: ProfileUiPreferenceUpdate,
    current_user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUiPreferenceResponse:
    """Updates layout customizations and hidden panel preferences for a profile."""
    profile = await _resolve_target_profile(profile_id, current_user, db)

    pref_res = await db.execute(
        select(ProfileUiPreference).where(ProfileUiPreference.profile_id == profile.id)
    )
    pref = pref_res.scalar_one_or_none()

    if pref is None:
        pref = ProfileUiPreference(
            profile_id=profile.id,
            hidden_panels=body.hidden_panels,
            theme_preference=body.theme_preference,
            updated_at=utc_now(),
        )
        db.add(pref)
    else:
        pref.hidden_panels = body.hidden_panels
        if body.theme_preference is not None:
            pref.theme_preference = body.theme_preference
        pref.updated_at = utc_now()

    await db.commit()
    await db.refresh(pref)

    return ProfileUiPreferenceResponse(
        profile_id=profile.id,
        hidden_panels=pref.hidden_panels or [],
        theme_preference=pref.theme_preference,
    )
