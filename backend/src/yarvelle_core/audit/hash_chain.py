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

"""Tamper-evident SHA-256 audit event hash chain per care profile (AU-78).

Links every `AuditEventRecord` row for a profile into an append-only
cryptographic hash chain anchored at `GENESIS_HASH = "GENESIS"`, enabling
deterministic detection of post-hoc row modification, deletion, or splicing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Dict, Optional, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.db.models import AuditEventRecord
from yarvelle_core.scope.context import DEFAULT_SCOPE

GENESIS_HASH: str = "GENESIS"


def compute_audit_entry_hash_v1(
    prev_hash: str,
    event_id: str,
    profile_id: Optional[str],
    event: str,
    tool: Optional[str],
    risk: Optional[str],
    decision: Optional[str],
    payload_hash: Optional[str],
) -> str:
    """Legacy 8-field SHA-256 hash for backwards compatibility with pre-migration records."""
    canonical = (
        f"{prev_hash or GENESIS_HASH}|"
        f"{event_id}|"
        f"{profile_id or ''}|"
        f"{event}|"
        f"{tool or ''}|"
        f"{risk or ''}|"
        f"{decision or ''}|"
        f"{payload_hash or ''}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_audit_entry_hash(
    prev_hash: str,
    event_id: str,
    profile_id: Optional[str],
    event: str,
    tool: Optional[str],
    risk: Optional[str],
    decision: Optional[str],
    payload_hash: Optional[str],
    scope: Optional[str] = DEFAULT_SCOPE,
    pack_id: Optional[str] = DEFAULT_SCOPE,
    risk_tier: Optional[str] = None,
) -> str:
    """Computes a deterministic SHA-256 hex digest over canonical audit event fields (11 fields).

    Canonical preimage format:
        `{prev_hash or GENESIS_HASH}|{event_id}|{profile_id or ''}|{event}|{tool or ''}|{risk or ''}|{decision or ''}|{payload_hash or ''}|{scope or DEFAULT_SCOPE}|{pack_id or DEFAULT_SCOPE}|{risk_tier or ''}`
    """
    canonical = (
        f"{prev_hash or GENESIS_HASH}|"
        f"{event_id}|"
        f"{profile_id or ''}|"
        f"{event}|"
        f"{tool or ''}|"
        f"{risk or ''}|"
        f"{decision or ''}|"
        f"{payload_hash or ''}|"
        f"{scope or DEFAULT_SCOPE}|"
        f"{pack_id or DEFAULT_SCOPE}|"
        f"{risk_tier or ''}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append_chained_audit_event(
    session: AsyncSession,
    *,
    profile_id: Optional[str],
    actor_user_id: Optional[str] = None,
    principal: str = "user",
    run_id: Optional[str] = None,
    event: str = "tool",
    tool: Optional[str] = None,
    risk: Optional[str] = None,
    decision: Optional[str] = "allow",
    payload_hash: Optional[str] = None,
    external_ref: Optional[str] = None,
    detail_redacted: Optional[str] = None,
    event_id: Optional[str] = None,
    scope: str = DEFAULT_SCOPE,
    pack_id: Optional[str] = None,
    risk_tier: Optional[str] = None,
) -> AuditEventRecord:
    """Appends a cryptographically chained `AuditEventRecord` to the profile's hash chain."""
    clean_profile_id = str(profile_id).strip() if profile_id else None

    stmt = (
        select(AuditEventRecord)
        .where(
            AuditEventRecord.profile_id == clean_profile_id,
            AuditEventRecord.entry_hash.is_not(None),
        )
        .order_by(AuditEventRecord.ts.desc(), AuditEventRecord.id.desc())
        .limit(1)
        .execution_options(include_all_scopes=True)
    )
    result = await session.execute(stmt)
    latest = result.scalar_one_or_none()

    prev_hash = latest.entry_hash if (latest and latest.entry_hash) else GENESIS_HASH
    new_id = str(event_id).strip() if event_id else str(uuid.uuid4())

    now_utc = datetime.now(timezone.utc)
    if latest is not None and latest.ts is not None:
        latest_ts = latest.ts if latest.ts.tzinfo else latest.ts.replace(tzinfo=timezone.utc)
        if now_utc <= latest_ts:
            now_utc = latest_ts + timedelta(microseconds=1)

    effective_scope = (scope or DEFAULT_SCOPE).strip()
    effective_pack_id = (pack_id or DEFAULT_SCOPE).strip()

    entry_hash = compute_audit_entry_hash(
        prev_hash=prev_hash,
        event_id=new_id,
        profile_id=clean_profile_id,
        event=event,
        tool=tool,
        risk=risk,
        decision=decision,
        payload_hash=payload_hash,
        scope=effective_scope,
        pack_id=effective_pack_id,
        risk_tier=risk_tier,
    )

    record = AuditEventRecord(
        id=new_id,
        ts=now_utc,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal=principal,
        run_id=run_id,
        event=event,
        tool=tool,
        risk=risk,
        decision=decision,
        payload_hash=payload_hash,
        external_ref=external_ref,
        detail_redacted=detail_redacted,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        scope=effective_scope,
        pack_id=effective_pack_id,
        risk_tier=risk_tier,
    )
    session.add(record)
    await session.flush()
    return record


async def verify_profile_audit_chain(
    session: AsyncSession,
    profile_id: str,
) -> Dict[str, Any]:
    """Verifies the cryptographic integrity of a profile's `AuditEventRecord` hash chain.

    Returns:
        Dictionary with `profile_id`, `valid`, `checked_count`, `head_hash`,
        `broken_at_event_id`, and `reason`.
    """
    clean_profile_id = (profile_id or "").strip()
    stmt = (
        select(AuditEventRecord)
        .where(
            AuditEventRecord.profile_id == clean_profile_id,
            AuditEventRecord.entry_hash.is_not(None),
        )
        .order_by(AuditEventRecord.ts.asc(), AuditEventRecord.id.asc())
        .execution_options(include_all_scopes=True)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    expected_prev = GENESIS_HASH
    for idx, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            return {
                "profile_id": clean_profile_id,
                "valid": False,
                "checked_count": idx + 1,
                "head_hash": None,
                "broken_at_event_id": row.id,
                "reason": "prev_hash_mismatch",
            }

        recomputed_hash = compute_audit_entry_hash(
            prev_hash=row.prev_hash or GENESIS_HASH,
            event_id=row.id,
            profile_id=row.profile_id,
            event=row.event,
            tool=row.tool,
            risk=row.risk,
            decision=row.decision,
            payload_hash=row.payload_hash,
            scope=row.scope,
            pack_id=row.pack_id,
            risk_tier=row.risk_tier,
        )
        if row.entry_hash != recomputed_hash:
            # Fallback to checking legacy 8-field hash for pre-migration records
            legacy_hash = compute_audit_entry_hash_v1(
                prev_hash=row.prev_hash or GENESIS_HASH,
                event_id=row.id,
                profile_id=row.profile_id,
                event=row.event,
                tool=row.tool,
                risk=row.risk,
                decision=row.decision,
                payload_hash=row.payload_hash,
            )
            if row.entry_hash != legacy_hash:
                return {
                    "profile_id": clean_profile_id,
                    "valid": False,
                    "checked_count": idx + 1,
                    "head_hash": None,
                    "broken_at_event_id": row.id,
                    "reason": "hash_mismatch",
                }

        expected_prev = row.entry_hash

    return {
        "profile_id": clean_profile_id,
        "valid": True,
        "checked_count": len(rows),
        "head_hash": rows[-1].entry_hash if rows else GENESIS_HASH,
        "broken_at_event_id": None,
        "reason": None,
    }


async def record_scope_cross_read_audit(
    session: Optional[AsyncSession] = None,
    *,
    reader_agent_id: str,
    reader_scope: str,
    target_agent_id: str,
    target_scope: str,
    claim_keys: Sequence[str],
    round_num: int,
    profile_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    pack_id: Optional[str] = None,
    panel_id: Optional[str] = None,
    session_factory: Optional[Any] = None,
) -> AuditEventRecord:
    """Records a tamper-evident SHA-256 hash-chained 'scope.cross_read' audit event.

    Enforces ADR 0001 §2.3 Rule 5:
        For every cross-scope read permitted by the blackboard, a tamper-evident
        SHA-256 hash-chained audit record is appended to the profile audit chain.
    """
    sorted_keys = sorted(list(claim_keys))
    payload: Dict[str, Any] = {
        "claim_keys": sorted_keys,
        "reader_agent_id": reader_agent_id,
        "reader_scope": reader_scope,
        "round_num": round_num,
        "source_scope": target_scope,
        "target_agent_id": target_agent_id,
        "target_scope": target_scope,
    }
    if panel_id:
        payload["panel_id"] = panel_id

    import json
    from yarvelle_core.audit.logger import compute_payload_hash

    payload_hash = compute_payload_hash(payload)
    detail_redacted = json.dumps(payload, sort_keys=True)

    if session is not None:
        return await append_chained_audit_event(
            session,
            profile_id=profile_id,
            actor_user_id=actor_user_id,
            principal="agent",
            run_id=run_id,
            event="scope.cross_read",
            tool=None,
            risk="read",
            decision="allow",
            payload_hash=payload_hash,
            detail_redacted=detail_redacted,
            scope=reader_scope,
            pack_id=pack_id or reader_scope,
            risk_tier="read",
        )

    from yarvelle_core.db.session import get_session_factory

    factory = session_factory or get_session_factory()
    async with factory() as sess:
        record = await append_chained_audit_event(
            sess,
            profile_id=profile_id,
            actor_user_id=actor_user_id,
            principal="agent",
            run_id=run_id,
            event="scope.cross_read",
            tool=None,
            risk="read",
            decision="allow",
            payload_hash=payload_hash,
            detail_redacted=detail_redacted,
            scope=reader_scope,
            pack_id=pack_id or reader_scope,
            risk_tier="read",
        )
        await sess.commit()
        return record

