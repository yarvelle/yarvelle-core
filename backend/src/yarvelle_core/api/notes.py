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

"""Profile-scoped and workspace-isolated REST API endpoints for Notes (Issue #65)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.connections import require_profile_access
from yarvelle_core.api.deps import (
    get_current_user,
    get_db,
    get_user_profile_access,
    resolve_owner_user_id,
)
from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.db.models import Note, Profile, ProfileAccess
from yarvelle_core.errors import YarvelleError

router = APIRouter(tags=["notes"], route_class=ProblemDetailsRoute)


# ============================================================================
# Section 1: Validation Helpers & Pydantic Schemas
# ============================================================================


def _validate_clean_string(v: Any, field_name: str) -> Any:
    if isinstance(v, str):
        if "\x00" in v:
            raise ValueError(f"Null bytes are forbidden in parameter '{field_name}'.")
        return unicodedata.normalize("NFC", v)
    return v


def _slugify(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", cleaned).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:120] if slug else f"note-{uuid.uuid4().hex[:8]}"


class CreateNoteRequest(BaseModel):
    """Payload for creating a profile-scoped workspace note."""

    title: str = Field(..., min_length=1, max_length=255, description="Note title")
    content: str = Field("", description="Markdown content of the note")
    type: str = Field("general", max_length=32, description="Note category: general, scratchpad, prep, summary")
    tags: List[str] = Field(default_factory=list, description="List of string tags")
    pinned: bool = Field(False, description="Whether the note is pinned")
    slug: Optional[str] = Field(None, max_length=128, description="Custom note slug or filename identifier")
    locale: Optional[str] = Field("en-US", max_length=16, description="IETF BCP 47 locale tag")
    profile_id: Optional[str] = Field(None, max_length=36, description="Optional profile ID binding")

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: Any) -> Any:
        return _validate_clean_string(v, "title")

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v: Any) -> Any:
        return _validate_clean_string(v, "content")

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, v: Any) -> Any:
        return _validate_clean_string(v, "type")

    @field_validator("slug", mode="before")
    @classmethod
    def validate_slug(cls, v: Any) -> Any:
        return _validate_clean_string(v, "slug")

    @field_validator("locale", mode="before")
    @classmethod
    def validate_locale(cls, v: Any) -> Any:
        return _validate_clean_string(v, "locale")

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v: Any) -> Any:
        if isinstance(v, list):
            clean_tags = []
            for tag in v:
                if isinstance(tag, str):
                    if "\x00" in tag:
                        raise ValueError("Null bytes are forbidden in tag items.")
                    clean_tags.append(unicodedata.normalize("NFC", tag.strip()))
            return clean_tags
        return v


class UpdateNoteRequest(BaseModel):
    """Payload for partially updating a note."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None)
    type: Optional[str] = Field(None, max_length=32)
    tags: Optional[List[str]] = Field(None)
    pinned: Optional[bool] = Field(None)
    slug: Optional[str] = Field(None, max_length=128)
    locale: Optional[str] = Field(None, max_length=16)

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v: Any) -> Any:
        return _validate_clean_string(v, "title")

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v: Any) -> Any:
        return _validate_clean_string(v, "content")

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, v: Any) -> Any:
        return _validate_clean_string(v, "type")

    @field_validator("slug", mode="before")
    @classmethod
    def validate_slug(cls, v: Any) -> Any:
        return _validate_clean_string(v, "slug")

    @field_validator("locale", mode="before")
    @classmethod
    def validate_locale(cls, v: Any) -> Any:
        return _validate_clean_string(v, "locale")

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v: Any) -> Any:
        if isinstance(v, list):
            clean_tags = []
            for tag in v:
                if isinstance(tag, str):
                    if "\x00" in tag:
                        raise ValueError("Null bytes are forbidden in tag items.")
                    clean_tags.append(unicodedata.normalize("NFC", tag.strip()))
            return clean_tags
        return v


# ============================================================================
# Section 2: Serialization Helpers
# ============================================================================


def serialize_note(note: Note) -> Dict[str, Any]:
    """Serializes a `Note` ORM instance into a JSON dictionary."""
    return {
        "id": note.id,
        "profile_id": note.profile_id,
        "user_id": note.user_id,
        "title": note.title,
        "content": note.content,
        "type": note.type,
        "tags": note.tags,
        "pinned": bool(note.pinned),
        "slug": note.slug,
        "locale": note.locale,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "linked_appointment_id": note.linked_appointment_id,
    }


# ============================================================================
# Section 3: Profile-Scoped Endpoints (/profiles/{profile_id}/notes)
# ============================================================================


@router.post(
    "/profiles/{profile_id}/notes",
    status_code=status.HTTP_201_CREATED,
    summary="Create a profile-scoped note",
)
async def create_profile_note(
    profile_id: str,
    payload: CreateNoteRequest,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Creates a new workspace note scoped strictly to `profile_id`."""
    actor_id = resolve_owner_user_id(user) or profile.user_id
    now = datetime.now(timezone.utc)
    note_id = str(uuid.uuid4())
    slug = (payload.slug or _slugify(payload.title))[:128]

    note = Note(
        id=note_id,
        user_id=actor_id,
        profile_id=profile.id,
        slug=slug,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        pinned=payload.pinned,
        locale=payload.locale or "en-US",
        tags_json=json.dumps(payload.tags or []),
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    return serialize_note(note)


@router.get(
    "/profiles/{profile_id}/notes",
    summary="List workspace notes for a profile with optional filtering",
)
async def list_profile_notes(
    profile_id: str,
    type: Optional[str] = Query(None, description="Filter by note category/type"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    pinned: Optional[bool] = Query(None, description="Filter by pinned status"),
    search: Optional[str] = Query(None, description="Full-text search query across title and content"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Lists notes matching profile and filters."""
    query = select(Note).where(Note.profile_id == profile.id)

    if type:
        query = query.where(Note.type == type.strip())
    if pinned is not None:
        query = query.where(Note.pinned == pinned)
    if tag:
        clean_tag = tag.strip()
        query = query.where(Note.tags_json.contains(f'"{clean_tag}"'))
    if search:
        s = f"%{search.strip()}%"
        query = query.where((Note.title.ilike(s)) | (Note.content.ilike(s)))

    count_stmt = select(func.count()).select_from(query.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar_one()

    query = query.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(limit).offset(offset)
    res = await db.execute(query)
    notes = res.scalars().all()
    items = [serialize_note(n) for n in notes]

    return {
        "notes": items,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/profiles/{profile_id}/notes/{note_id}",
    summary="Get single note by ID for a profile",
)
async def get_profile_note(
    profile_id: str,
    note_id: str,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Fetches a single workspace note scoped to `profile_id`."""
    stmt = select(Note).where(Note.id == note_id.strip(), Note.profile_id == profile.id)
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id, "profile_id": profile.id},
        )
    return serialize_note(note)


@router.patch(
    "/profiles/{profile_id}/notes/{note_id}",
    summary="Update an existing workspace note",
)
async def update_profile_note(
    profile_id: str,
    note_id: str,
    payload: UpdateNoteRequest,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Partially updates an existing workspace note."""
    stmt = select(Note).where(Note.id == note_id.strip(), Note.profile_id == profile.id)
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id, "profile_id": profile.id},
        )

    if payload.title is not None:
        note.title = payload.title
    if payload.content is not None:
        note.content = payload.content
    if payload.type is not None:
        note.type = payload.type
    if payload.pinned is not None:
        note.pinned = payload.pinned
    if payload.tags is not None:
        note.set_tags(payload.tags)
    if payload.slug is not None:
        note.slug = payload.slug
    if payload.locale is not None:
        note.locale = payload.locale

    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(note)

    return serialize_note(note)


@router.delete(
    "/profiles/{profile_id}/notes/{note_id}",
    summary="Delete a workspace note",
)
async def delete_profile_note(
    profile_id: str,
    note_id: str,
    profile: Profile = Depends(require_profile_access("view_records")),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Deletes a workspace note scoped to `profile_id`."""
    stmt = select(Note).where(Note.id == note_id.strip(), Note.profile_id == profile.id)
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id, "profile_id": profile.id},
        )

    await db.delete(note)
    await db.commit()

    return {
        "success": True,
        "id": note_id,
        "deleted": True,
    }


# ============================================================================
# Section 4: Direct /notes Endpoints (Convenience & E2E Test Compatibility)
# ============================================================================


async def _verify_note_profile_access(
    note: Note,
    user: UserProfile,
    db: AsyncSession,
) -> None:
    """Verifies that the current user has access to the profile owning this note."""
    if note.profile_id:
        p_stmt = select(Profile).where(Profile.id == note.profile_id)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is None:
            raise YarvelleError("YRV-500-005", context={"note_id": note.id})
        access = await get_user_profile_access(prof, user, db)
        if access is None:
            raise YarvelleError(
                "YRV-300-007",
                context={"note_id": note.id, "profile_id": note.profile_id},
                detail="Access denied: you do not have permission for this profile's notes.",
            )
    else:
        owner_id = resolve_owner_user_id(user)
        effective_user_id = owner_id or user.id
        if note.user_id and note.user_id != effective_user_id:
            raise YarvelleError(
                "YRV-300-007",
                context={"note_id": note.id},
                detail="Access denied: you do not have permission for this note.",
            )


@router.post(
    "/notes",
    status_code=status.HTTP_201_CREATED,
    summary="Create a note (direct path)",
)
async def post_direct_note(
    payload: CreateNoteRequest,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Direct `/notes` endpoint with explicit or fallback `profile_id`."""
    actor_id = resolve_owner_user_id(user) or user.id
    target_profile_id = (payload.profile_id or "").strip()

    if not target_profile_id:
        stmt = select(Profile)
        if actor_id:
            stmt = stmt.where(Profile.user_id == actor_id)
        stmt = stmt.order_by(Profile.created_at.asc())
        res = await db.execute(stmt)
        p = res.scalars().first()
        if p is None:
            raise YarvelleError("YRV-500-002", context={"profile_id": "default"})
        target_profile_id = p.id
    else:
        stmt = select(Profile).where(Profile.id == target_profile_id)
        res = await db.execute(stmt)
        p = res.scalar_one_or_none()
        if p is None:
            raise YarvelleError("YRV-500-002", context={"profile_id": target_profile_id})
        access = await get_user_profile_access(p, user, db)
        if access is None:
            raise YarvelleError(
                "YRV-300-007",
                context={"profile_id": target_profile_id},
                detail="Access denied: you do not have permission for this profile.",
            )

    now = datetime.now(timezone.utc)
    note_id = str(uuid.uuid4())
    slug = (payload.slug or _slugify(payload.title))[:128]

    note = Note(
        id=note_id,
        user_id=actor_id,
        profile_id=target_profile_id,
        slug=slug,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        pinned=payload.pinned,
        locale=payload.locale or "en-US",
        tags_json=json.dumps(payload.tags or []),
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    return serialize_note(note)


@router.get(
    "/notes",
    summary="List notes (direct path)",
)
async def get_direct_notes(
    profile_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    pinned: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Direct `/notes` listing endpoint."""
    query = select(Note)
    if profile_id:
        clean_pid = profile_id.strip()
        p_stmt = select(Profile).where(Profile.id == clean_pid)
        p_res = await db.execute(p_stmt)
        prof = p_res.scalar_one_or_none()
        if prof is None:
            raise YarvelleError("YRV-500-002", context={"profile_id": clean_pid})
        access = await get_user_profile_access(prof, user, db)
        if access is None:
            raise YarvelleError(
                "YRV-300-007",
                context={"profile_id": clean_pid},
                detail="Access denied: you do not have permission for this profile.",
            )
        query = query.where(Note.profile_id == clean_pid)
    else:
        owner_id = resolve_owner_user_id(user)
        effective_user_id = owner_id or user.id
        if owner_id is None and user.id == DEFAULT_STEWARD_USER.id:
            pass
        else:
            accessible_profiles_subq = (
                select(Profile.id)
                .outerjoin(ProfileAccess, Profile.id == ProfileAccess.profile_id)
                .where(
                    (Profile.user_id == effective_user_id)
                    | (ProfileAccess.user_id == effective_user_id)
                )
            )
            query = query.where(
                (Note.profile_id.in_(accessible_profiles_subq))
                | ((Note.user_id == effective_user_id) & (Note.profile_id.is_(None)))
            )

    if type:
        query = query.where(Note.type == type.strip())
    if pinned is not None:
        query = query.where(Note.pinned == pinned)
    if tag:
        clean_tag = tag.strip()
        query = query.where(Note.tags_json.contains(f'"{clean_tag}"'))
    if search:
        s = f"%{search.strip()}%"
        query = query.where((Note.title.ilike(s)) | (Note.content.ilike(s)))

    count_stmt = select(func.count()).select_from(query.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar_one()

    query = query.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(limit).offset(offset)
    res = await db.execute(query)
    notes = res.scalars().all()
    items = [serialize_note(n) for n in notes]

    return {
        "notes": items,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/notes/{note_id}",
    summary="Get single note by ID (direct path)",
)
async def get_direct_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fetches note by `note_id` with profile access validation."""
    stmt = select(Note).where(Note.id == note_id.strip())
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id},
        )
    await _verify_note_profile_access(note, user, db)
    return serialize_note(note)


@router.patch(
    "/notes/{note_id}",
    summary="Update note by ID (direct path)",
)
async def patch_direct_note(
    note_id: str,
    payload: UpdateNoteRequest,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Partially updates note by `note_id` with profile access validation."""
    stmt = select(Note).where(Note.id == note_id.strip())
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id},
        )
    await _verify_note_profile_access(note, user, db)

    if payload.title is not None:
        note.title = payload.title
    if payload.content is not None:
        note.content = payload.content
    if payload.type is not None:
        note.type = payload.type
    if payload.pinned is not None:
        note.pinned = payload.pinned
    if payload.tags is not None:
        note.set_tags(payload.tags)
    if payload.slug is not None:
        note.slug = payload.slug
    if payload.locale is not None:
        note.locale = payload.locale

    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(note)

    return serialize_note(note)


@router.delete(
    "/notes/{note_id}",
    summary="Delete note by ID (direct path)",
)
async def delete_direct_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
) -> Dict[str, Any]:
    """Deletes note by `note_id` with profile access validation."""
    stmt = select(Note).where(Note.id == note_id.strip())
    res = await db.execute(stmt)
    note = res.scalar_one_or_none()
    if note is None:
        raise YarvelleError(
            "YRV-500-005",
            context={"note_id": note_id},
        )
    await _verify_note_profile_access(note, user, db)

    await db.delete(note)
    await db.commit()

    return {
        "success": True,
        "id": note_id,
        "deleted": True,
    }


__all__ = [
    "CreateNoteRequest",
    "UpdateNoteRequest",
    "router",
    "serialize_note",
]
