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

"""Audit logging schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

OrchestrationAuditEventType = Literal[
    "route.user_selected",
    "route.fixed",
    "route.default",
    "route.main_agent",
    "route.classified",
    "route.rejected",
    "task.started",
    "task.completed",
    "task.failed",
    "task.timed_out",
    "task.cancelled",
]
"""Multi-agent orchestration events.

``route.*`` events carry a ``RouteDecision`` under ``details["route"]``
(``RouteDecision.to_audit_payload()``), except ``route.rejected``: a caller
picked an agent that may not be picked directly (hidden or unknown), and
``details["rejected_pick"]`` names it and why. The turn's own ``route.*``
record follows. ``task.*`` events describe one subagent
hand-off (one ``task`` tool call) and set ``task_id`` and ``agent_id``.
"""

AuditEventType = Literal[
    "run",
    "tool",
    "refuse",
    "error",
    "boundary_warning",
    "synthesis",
    "scope.cross_read",
    "route.user_selected",
    "route.fixed",
    "route.default",
    "route.main_agent",
    "route.classified",
    "route.rejected",
    "task.started",
    "task.completed",
    "task.failed",
    "task.timed_out",
    "task.cancelled",
]

AuditDurability = Literal["strict", "best_effort"]

_STRICT_PREFIXES = ("route.", "task.")


def audit_durability(event: str) -> AuditDurability:
    """Returns how an audit write must be treated.

    ``strict`` events (orchestration routes and hand-offs) must be recorded
    before the turn continues; a failed write stops the turn. Every other
    event keeps the existing best-effort behaviour.
    """
    return "strict" if event.startswith(_STRICT_PREFIXES) else "best_effort"


class AuditEvent(BaseModel):
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent_id: str
    skill_id: Optional[str] = None
    skill_version: Optional[str] = None
    event: AuditEventType
    tool: Optional[str] = None
    allowed: Optional[bool] = None
    reason: Optional[str] = None
    duration_ms: Optional[float] = None
    prompt: Optional[str] = None      # Redacted unless store_bodies=True
    completion: Optional[str] = None  # Redacted unless store_bodies=True
    thread_id: Optional[str] = None
    profile_id: Optional[str] = None
    id: Optional[str] = None
    actor_user_id: Optional[str] = None
    principal: Optional[str] = None
    run_id: Optional[str] = None
    risk: Optional[str] = None
    decision: Optional[str] = None
    payload_hash: Optional[str] = None
    external_ref: Optional[str] = None
    scope: Optional[str] = None
    pack_id: Optional[str] = None
    risk_tier: Optional[str] = None
    # Orchestration hand-off fields (``task.*`` / ``route.*`` events)
    turn_id: Optional[str] = None
    task_id: Optional[str] = Field(default=None, description="Id of the task tool call that started the subagent.")
    parent_task_id: Optional[str] = None
    input_hash: Optional[str] = Field(default=None, pattern=SHA256_HEX_PATTERN)
    output_hash: Optional[str] = Field(default=None, pattern=SHA256_HEX_PATTERN)
    error_code: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_.-]{1,64}$")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Event-specific, already-redacted fields.")


class AuditListResponse(BaseModel):
    total: int
    limit: int
    events: List[AuditEvent]
