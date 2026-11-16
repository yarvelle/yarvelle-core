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

"""Closed tools for reminders: create (with Job scheduling) and list (AU-28)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from yarvelle_core.audit.logger import record_audit
from yarvelle_core.db.models import Job, Reminder
from yarvelle_core.db.session import get_session_factory
from yarvelle_core.schemas.tool import ToolResult

logger = logging.getLogger("yarvelle_core.tools.reminders")

VALID_REMINDER_CATEGORIES = {"task", "event", "prep", "general", "appointment"}


def register_reminder_category(category: str) -> None:
    """Registers an additional domain-specific reminder category."""
    VALID_REMINDER_CATEGORIES.add(category.strip().lower())


async def execute_create_reminder(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Creates a new reminder and enqueues matching wall-clock Job with fail-closed security."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("create_reminder rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed create_reminder.",
        )
    clean_profile_id = profile_id.strip()

    title = str(args.get("title", "")).strip() if isinstance(args, dict) else ""
    if not title:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'title' must be a non-empty string.",
        )

    due_raw = args.get("next_due_at") if isinstance(args, dict) else None
    if not due_raw:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'next_due_at' must be a valid ISO-8601 timestamp.",
        )

    try:
        due_dt = datetime.fromisoformat(str(due_raw))
    except Exception as exc:
        return ToolResult(
            success=False,
            output=None,
            error=f"Parameter 'next_due_at' must be a valid ISO-8601 timestamp: {exc}",
        )

    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=timezone.utc)

    category = str(args.get("category", "general")).strip().lower() if isinstance(args, dict) else "general"
    if category not in VALID_REMINDER_CATEGORIES:
        allowed_cats = ", ".join(sorted(VALID_REMINDER_CATEGORIES))
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid reminder category '{category}'. Allowed categories: {allowed_cats}.",
        )

    tz_str = str(args.get("timezone", "UTC")).strip() if isinstance(args, dict) else "UTC"
    tz_str = tz_str or "UTC"
    try:
        ZoneInfo(tz_str)
    except Exception:
        return ToolResult(
            success=False,
            output=None,
            error=f"Invalid IANA timezone identifier: '{tz_str}'.",
        )

    rrule_raw = args.get("rrule") if isinstance(args, dict) else None
    clean_rrule: Optional[str] = None
    if rrule_raw:
        clean_rrule = str(rrule_raw).strip()
        if "FREQ=" not in clean_rrule.upper():
            return ToolResult(
                success=False,
                output=None,
                error="Invalid RFC 5545 RRULE syntax. Must include FREQ token (e.g. 'FREQ=DAILY;INTERVAL=1').",
            )

    rem_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    due_utc = due_dt.astimezone(timezone.utc)

    factory = get_session_factory()
    async with factory() as session:
        reminder = Reminder(
            id=rem_id,
            profile_id=clean_profile_id,
            title=title,
            description=args.get("description") if isinstance(args, dict) else None,
            category=category,
            rrule=clean_rrule,
            timezone=tz_str,
            next_due_at=due_utc,
            status="pending",
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(reminder)

        # Enqueue corresponding wall-clock Job in jobs table
        job = Job(
            id=job_id,
            profile_id=clean_profile_id,
            kind="reminder",
            payload=json.dumps({"reminder_id": rem_id}),
            timezone=tz_str,
            rrule=clean_rrule,
            next_run_at=due_utc,
            status="pending",
            idempotency_key=f"reminder:{rem_id}",
            attempts=0,
            created_at=now_utc,
            updated_at=now_utc,
        )
        session.add(job)
        await session.commit()

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "create",
                "tool": "create_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem_id}",
                "details": {
                    "title": title,
                    "category": category,
                    "next_due_at": due_utc.isoformat(),
                    "rrule": clean_rrule,
                },
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for reminder %s: %s", rem_id, audit_err)

    return ToolResult(
        success=True,
        output={
            "id": rem_id,
            "job_id": job_id,
            "profile_id": clean_profile_id,
            "title": title,
            "description": args.get("description") if isinstance(args, dict) else None,
            "category": category,
            "rrule": clean_rrule,
            "timezone": tz_str,
            "next_due_at": due_utc.isoformat(),
            "status": "pending",
            "undo_reference": f"reminder:{rem_id}",
        },
    )


async def execute_list_reminders(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Queries reminders for a profile."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        logger.warning("list_reminders rejected: missing or invalid profile_id in ToolContext")
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required; profile_id must be a non-empty string for fail-closed list_reminders.",
        )
    clean_profile_id = profile_id.strip()

    status_filter = args.get("status") if isinstance(args, dict) else None
    category_filter = args.get("category") if isinstance(args, dict) else None
    due_before = args.get("due_before") if isinstance(args, dict) else None
    limit = int(args.get("limit", 50)) if isinstance(args, dict) else 50
    offset = int(args.get("offset", 0)) if isinstance(args, dict) else 0

    limit = max(1, min(100, limit))
    offset = max(0, offset)

    factory = get_session_factory()
    async with factory() as session:
        query = select(Reminder).where(Reminder.profile_id == clean_profile_id)

        if status_filter:
            query = query.where(Reminder.status == str(status_filter).strip().lower())
        if category_filter:
            query = query.where(Reminder.category == str(category_filter).strip().lower())
        if due_before:
            try:
                dt_before = datetime.fromisoformat(str(due_before))
                if dt_before.tzinfo is None:
                    dt_before = dt_before.replace(tzinfo=timezone.utc)
                query = query.where(Reminder.next_due_at <= dt_before.astimezone(timezone.utc))
            except Exception:
                pass

        count_stmt = select(func.count()).select_from(query.subquery())
        count_res = await session.execute(count_stmt)
        total_count = count_res.scalar_one()

        query = query.order_by(Reminder.next_due_at.asc()).limit(limit).offset(offset)
        res = await session.execute(query)
        records = list(res.scalars().all())

    reminders_list = [
        {
            "id": r.id,
            "profile_id": r.profile_id,
            "title": r.title,
            "description": r.description,
            "category": r.category,
            "rrule": r.rrule,
            "timezone": r.timezone,
            "next_due_at": r.next_due_at.isoformat() if r.next_due_at else None,
            "status": r.status,
            "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
            "snooze_until": r.snooze_until.isoformat() if r.snooze_until else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in records
    ]

    return ToolResult(
        success=True,
        output={
            "reminders": reminders_list,
            "total": total_count,
            "limit": limit,
            "offset": offset,
        },
    )


async def execute_update_reminder(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Updates an existing reminder scoped to `profile_id`."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required in ToolContext for update_reminder.",
        )
    clean_profile_id = profile_id.strip()

    rem_id = str(args.get("id") or args.get("reminder_id") or "").strip()
    if not rem_id:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'id' (or 'reminder_id') is required for update_reminder.",
        )

    factory = get_session_factory()
    now_utc = datetime.now(timezone.utc)
    updated_dict: Dict[str, Any] = {}

    async with factory() as session:
        stmt = select(Reminder).where(
            Reminder.id == rem_id,
            Reminder.profile_id == clean_profile_id,
        )
        res = await session.execute(stmt)
        reminder = res.scalar_one_or_none()
        if reminder is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Reminder '{rem_id}' not found for profile '{clean_profile_id}'.",
            )

        if "title" in args and args["title"]:
            reminder.title = str(args["title"]).strip()
        if "description" in args:
            reminder.description = str(args["description"]).strip() if args["description"] else None
        if "category" in args and args["category"]:
            cat = str(args["category"]).strip().lower()
            if cat in VALID_REMINDER_CATEGORIES:
                reminder.category = cat
        if "status" in args and args["status"]:
            st = str(args["status"]).strip().lower()
            if st in ("pending", "snoozed", "completed", "missed", "cancelled"):
                reminder.status = st
        if "next_due_at" in args and args["next_due_at"]:
            try:
                due_dt = datetime.fromisoformat(str(args["next_due_at"]))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                reminder.next_due_at = due_dt.astimezone(timezone.utc)
            except Exception as exc:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Invalid ISO-8601 next_due_at: {exc}",
                )

        reminder.updated_at = now_utc

        # If next_due_at was updated, sync corresponding job
        if reminder.next_due_at:
            job_stmt = select(Job).where(
                Job.profile_id == clean_profile_id,
                Job.idempotency_key == f"reminder:{rem_id}",
            )
            job_res = await session.execute(job_stmt)
            job = job_res.scalar_one_or_none()
            if job:
                job.next_run_at = reminder.next_due_at
                job.updated_at = now_utc

        await session.commit()
        await session.refresh(reminder)

        updated_dict = {
            "id": reminder.id,
            "profile_id": reminder.profile_id,
            "title": reminder.title,
            "description": reminder.description,
            "category": reminder.category,
            "rrule": reminder.rrule,
            "timezone": reminder.timezone,
            "next_due_at": reminder.next_due_at.isoformat() if reminder.next_due_at else None,
            "status": reminder.status,
            "updated_at": reminder.updated_at.isoformat() if reminder.updated_at else None,
        }

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "update",
                "tool": "update_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem_id}",
                "details": updated_dict,
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for reminder update %s: %s", rem_id, audit_err)

    return ToolResult(success=True, output=updated_dict)


async def execute_delete_reminder(args: Dict[str, Any], ctx: Any = None) -> ToolResult:
    """Deletes an existing reminder and associated job scoped to `profile_id`."""
    profile_id = getattr(ctx, "profile_id", None) if ctx is not None else None
    if not profile_id or not isinstance(profile_id, str) or not profile_id.strip():
        return ToolResult(
            success=False,
            output=None,
            error="Security violation: profile_id is required in ToolContext for delete_reminder.",
        )
    clean_profile_id = profile_id.strip()

    rem_id = str(args.get("id") or args.get("reminder_id") or "").strip()
    if not rem_id:
        return ToolResult(
            success=False,
            output=None,
            error="Parameter 'id' (or 'reminder_id') is required for delete_reminder.",
        )

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Reminder).where(
            Reminder.id == rem_id,
            Reminder.profile_id == clean_profile_id,
        )
        res = await session.execute(stmt)
        reminder = res.scalar_one_or_none()
        if reminder is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Reminder '{rem_id}' not found for profile '{clean_profile_id}'.",
            )

        job_stmt = select(Job).where(
            Job.profile_id == clean_profile_id,
            Job.idempotency_key == f"reminder:{rem_id}",
        )
        job_res = await session.execute(job_stmt)
        job = job_res.scalar_one_or_none()
        if job:
            await session.delete(job)

        await session.delete(reminder)
        await session.commit()

    actor_id = getattr(ctx, "user_id", "user") or "user"
    try:
        await record_audit(
            {
                "profile_id": clean_profile_id,
                "action": "delete",
                "tool": "delete_reminder",
                "risk": "write_local",
                "external_ref": f"reminder:{rem_id}",
            },
            actor_user_id=actor_id,
            risk="write_local",
        )
    except Exception as audit_err:
        logger.debug("Audit logging failed for reminder delete %s: %s", rem_id, audit_err)

    return ToolResult(
        success=True,
        output={
            "id": rem_id,
            "deleted": True,
            "profile_id": clean_profile_id,
        },
    )


__all__ = [
    "VALID_REMINDER_CATEGORIES",
    "register_reminder_category",
    "execute_create_reminder",
    "execute_list_reminders",
    "execute_update_reminder",
    "execute_delete_reminder",
]
