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

"""Audit log retrieval and inspection endpoints with database-backed profile access scoping."""

from __future__ import annotations

import json
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Query

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.api.deps import get_current_user, resolve_owner_user_id
from yarvelle_core.api.errors import ProblemDetailsRoute
from yarvelle_core.api.profiles import get_user_profile_access
from yarvelle_core.audit.logger import get_recent_audit_events, open_audit_detail
from yarvelle_core.errors import YarvelleError
from yarvelle_core.vault.field_crypto import (
    FieldDecryptionError,
    FieldKeyError,
    PlaintextFieldError,
    is_sealed_text,
)
from yarvelle_core.auth.ports import UserProfile
from yarvelle_core.constants.api import ROUTE_AUDIT
from yarvelle_core.constants.agents import UNKNOWN_AGENT_ID
from yarvelle_core.constants.defaults import (
    DEFAULT_AUDIT_LIMIT,
    MAX_AUDIT_LIMIT,
    MIN_AUDIT_LIMIT,
)
from yarvelle_core.db.models import AuditEventRecord, Profile, ProfileAccess
from yarvelle_core.db.session import get_db
from yarvelle_core.config import settings
from yarvelle_core.schemas.audit import AuditEvent, AuditListResponse

router = APIRouter(tags=["Audit"], route_class=ProblemDetailsRoute)


def _record_to_schema(record: AuditEventRecord, full: bool = False) -> AuditEvent:
    """Converts a database AuditEventRecord to the API AuditEvent schema."""
    meta: dict[str, Any] = {}
    if record.detail_redacted:
        opened = open_audit_detail(
            record.detail_redacted,
            record_id=record.id,
            profile_id=record.profile_id,
            event_type=str(record.event),
            run_id=record.run_id,
        )
        if opened:
            try:
                meta = json.loads(opened)
            except json.JSONDecodeError:
                # Legacy/plaintext malformed JSON stays empty; sealed decrypt failures
                # raise above and must not be swallowed.
                if is_sealed_text(record.detail_redacted):
                    raise
                meta = {}

    agent_id = meta.get("agent_id") or record.principal or UNKNOWN_AGENT_ID
    allowed = meta.get("allowed")
    if allowed is None and record.decision:
        allowed = (record.decision == "allow")

    prompt = meta.get("prompt") if full else None
    completion = meta.get("completion") if full else None

    if hasattr(record.ts, "isoformat"):
        ts_str = record.ts.isoformat()
    else:
        ts_str = str(record.ts)

    return AuditEvent(
        id=record.id,
        ts=ts_str,
        agent_id=agent_id,
        skill_id=meta.get("skill_id"),
        skill_version=meta.get("skill_version"),
        event=record.event,  # type: ignore
        tool=record.tool,
        allowed=allowed,
        reason=meta.get("reason"),
        duration_ms=meta.get("duration_ms"),
        prompt=prompt,
        completion=completion,
        thread_id=record.run_id or meta.get("thread_id"),
        profile_id=record.profile_id,
        actor_user_id=record.actor_user_id,
        principal=record.principal,
        run_id=record.run_id,
        risk=record.risk,
        decision=record.decision,
        payload_hash=record.payload_hash,
        external_ref=record.external_ref,
    )


@router.get(ROUTE_AUDIT, response_model=AuditListResponse)
async def list_audit_events(
    limit: int = Query(
        DEFAULT_AUDIT_LIMIT,
        ge=MIN_AUDIT_LIMIT,
        le=MAX_AUDIT_LIMIT,
        description="Max number of recent events to return",
    ),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    event: Optional[str] = Query(None, description="Filter by event type (run, tool, refuse, error)"),
    full: bool = Query(False, description="Include message bodies if stored"),
    profile_id: Optional[str] = Query(None, description="Filter by profile ID"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """Retrieves recent audit log events directly from SQL audit_events with strict profile scoping."""
    try:
        query = select(AuditEventRecord)

        # 1. Profile Scoping
        if profile_id:
            p_res = await db.execute(select(Profile).where(Profile.id == profile_id))
            prof = p_res.scalar_one_or_none()
            if prof is None:
                raise YarvelleError(
                    "YRV-500-002",
                    context={"profile_id": profile_id},
                )

            access = await get_user_profile_access(prof, user, db)
            if access is None:
                raise YarvelleError(
                    "YRV-300-007",
                    context={"profile_id": profile_id},
                    detail=f"Forbidden: access denied for profile '{profile_id}'.",
                )

            query = query.where(AuditEventRecord.profile_id == profile_id)
        else:
            # Profile ID omitted: strictly filter to accessible profiles and caller's actions
            owner_id = resolve_owner_user_id(user)
            effective_user_id = owner_id or user.id

            if owner_id:
                acc_stmt = (
                    select(Profile.id)
                    .outerjoin(ProfileAccess, Profile.id == ProfileAccess.profile_id)
                    .where(
                        (Profile.user_id == owner_id)
                        | (ProfileAccess.user_id == effective_user_id)
                    )
                    .distinct()
                )
            else:
                acc_stmt = (
                    select(Profile.id)
                    .outerjoin(ProfileAccess, Profile.id == ProfileAccess.profile_id)
                    .where(
                        (Profile.user_id.is_(None))
                        | (Profile.user_id == user.id)
                        | (ProfileAccess.user_id == effective_user_id)
                    )
                    .distinct()
                )

            acc_res = await db.execute(acc_stmt)
            accessible_profile_ids = list(acc_res.scalars().all())

            scoping_clauses = []
            if accessible_profile_ids:
                scoping_clauses.append(AuditEventRecord.profile_id.in_(accessible_profile_ids))
            if effective_user_id:
                scoping_clauses.append(AuditEventRecord.actor_user_id == effective_user_id)
            if owner_id is None:
                scoping_clauses.append(
                    (AuditEventRecord.profile_id.is_(None)) & (AuditEventRecord.actor_user_id.is_(None))
                )

            if scoping_clauses:
                query = query.where(or_(*scoping_clauses))
            else:
                query = query.where(AuditEventRecord.id == "__no_matching_records__")

        # 2. Additional Query Filters
        if event:
            query = query.where(AuditEventRecord.event == event)

        encrypting = bool(getattr(settings, "audit_encryption", False))
        if agent_id and not encrypting:
            query = query.where(
                or_(
                    AuditEventRecord.detail_redacted.contains(f'"agent_id": "{agent_id}"'),
                    AuditEventRecord.principal == agent_id,
                )
            )

        # 3. Count + page. When encryption is on and agent_id is requested, agent_id
        # may live only inside sealed detail JSON, so every scoped row is considered
        # (no arbitrary fetch cap); exact total is computed after decrypt/filter.
        if agent_id and encrypting:
            records_stmt = query.order_by(AuditEventRecord.ts.desc())
            records_res = await db.execute(records_stmt)
            candidates = list(records_res.scalars().all())
            matched: list[AuditEventRecord] = []
            for r in candidates:
                if r.principal == agent_id:
                    matched.append(r)
                    continue
                detail = r.detail_redacted or ""
                if detail and not is_sealed_text(detail):
                    # Legacy plaintext row: retain prior SQL-equivalent contains check.
                    if f'"agent_id": "{agent_id}"' in detail:
                        matched.append(r)
                    continue
                schema = _record_to_schema(r, full=False)
                if schema.agent_id == agent_id:
                    matched.append(r)
            total = len(matched)
            page = matched[:limit]
            events = [_record_to_schema(r, full=full) for r in page]
        else:
            count_stmt = select(func.count()).select_from(query.subquery())
            total_res = await db.execute(count_stmt)
            total = total_res.scalar_one()

            records_stmt = query.order_by(AuditEventRecord.ts.desc()).limit(limit)
            records_res = await db.execute(records_stmt)
            records = list(records_res.scalars().all())

            events = [_record_to_schema(r, full=full) for r in records]

        return AuditListResponse(
            total=total,
            limit=limit,
            events=events,
        )
    except (FieldDecryptionError, FieldKeyError, PlaintextFieldError) as err:
        raise YarvelleError(
            "YRV-400-005",
            cause=err,
        ) from err
    except YarvelleError:
        raise
    except Exception as err:
        if "no such table" in str(err).lower():
            total, events = await get_recent_audit_events(
                limit=limit,
                agent_id=agent_id,
                event=event,
                full=full,
                profile_id=profile_id,
            )
            return AuditListResponse(
                total=total,
                limit=limit,
                events=events,
            )
        raise
