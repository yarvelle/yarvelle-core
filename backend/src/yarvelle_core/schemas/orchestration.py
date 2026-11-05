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

"""Typed, versioned data contracts for multi-agent orchestration.

Turns use hybrid routing (ADR-0005):

1. Pack-declared fixed routes are evaluated deterministically before any
   model call (``PackOrchestrationSpec.fixed_routes``).
2. Every other turn goes to the main Deep Agents agent, which delegates to
   registered subagents through its built-in ``task`` tool. There is no
   up-front plan model: the main agent's ``task`` calls are the plan.

This module holds only what LangGraph / Deep Agents do not provide:

- ``PackOrchestrationSpec``: pack-declared default agent, fixed routes and
  limits (the ``orchestration:`` block in ``pack.yaml``).
- ``OrchestrationLimits``: fan-out and timeout bounds, overridable per pack.
- ``RouteDecision``: how a turn was routed; carried in the audit payload of
  ``route.*`` events (see ``yarvelle_core.schemas.audit``).
- Stream status events for subagent tasks and user-visible notices.

The module is data-only. Agent ids are opaque slugs supplied by packs; core
never names a specific agent here.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yarvelle_core.schemas.manifest import SLUG_REGEX

ORCHESTRATION_SCHEMA_VERSION: Literal[1] = 1
"""Current version of every versioned contract in this module."""

ROUTE_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"

DEFAULT_MAX_AGENTS = 4
DEFAULT_AGENT_TIMEOUT_S = 60.0
DEFAULT_TURN_TIMEOUT_S = 120.0


def _check_agent_id(v: str) -> str:
    if not v or not SLUG_REGEX.match(v):
        raise ValueError(f"Invalid agent id '{v}': must match {SLUG_REGEX.pattern}")
    return v


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


class OrchestrationLimits(_Strict):
    """Per-turn bounds on subagent fan-out and wall-clock time."""

    max_agents: int = Field(
        default=DEFAULT_MAX_AGENTS,
        ge=1,
        le=16,
        description="Maximum number of subagent task calls in one turn.",
    )
    agent_timeout_s: float = Field(
        default=DEFAULT_AGENT_TIMEOUT_S,
        gt=0,
        description="Wall-clock timeout for a single subagent task, in seconds.",
    )
    turn_timeout_s: float = Field(
        default=DEFAULT_TURN_TIMEOUT_S,
        gt=0,
        description="Wall-clock budget for the whole turn, in seconds.",
    )

    @model_validator(mode="after")
    def _agent_within_turn(self) -> OrchestrationLimits:
        if self.agent_timeout_s > self.turn_timeout_s:
            raise ValueError("agent_timeout_s cannot exceed turn_timeout_s")
        return self


# ---------------------------------------------------------------------------
# Pack routing config
# ---------------------------------------------------------------------------


class HasAttachmentsTrigger(_Strict):
    """Fires when the user turn carries attachments, optionally of given media types."""

    kind: Literal["has_attachments"] = "has_attachments"
    mime_types: List[str] = Field(
        default_factory=list,
        description="Optional media types or 'type/*' wildcards; empty matches any attachment.",
    )

    @field_validator("mime_types")
    @classmethod
    def _check_mime(cls, v: List[str]) -> List[str]:
        for m in v:
            if "/" not in m or m.startswith("/") or m.endswith("/"):
                raise ValueError(f"Invalid media type '{m}'")
        return v


class GuardrailFlagTrigger(_Strict):
    """Fires when the input guardrail raises the named flag."""

    kind: Literal["guardrail_flag"] = "guardrail_flag"
    flag: str = Field(..., pattern=ROUTE_ID_PATTERN)


RouteTrigger = Annotated[Union[HasAttachmentsTrigger, GuardrailFlagTrigger], Field(discriminator="kind")]


class FixedRoute(_Strict):
    """A pack-declared deterministic route, evaluated before the main agent, in declared order."""

    route_id: str = Field(..., pattern=ROUTE_ID_PATTERN)
    when: RouteTrigger
    agent_id: str
    description: str = ""

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)


class PackOrchestrationSpec(_Strict):
    """Pack-level orchestration config (``orchestration:`` in pack.yaml).

    ``default_agent`` handles the turn when no model is configured (after fixed
    routes) and when the main agent cannot run; both cases carry a
    user-visible notice. It is never substituted silently for an unknown id.
    """

    schema_version: Literal[1] = ORCHESTRATION_SCHEMA_VERSION
    default_agent: str
    fixed_routes: List[FixedRoute] = Field(default_factory=list)
    limits: OrchestrationLimits = Field(default_factory=OrchestrationLimits)

    @field_validator("default_agent")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)

    @model_validator(mode="after")
    def _check_routes(self) -> PackOrchestrationSpec:
        ids = [r.route_id for r in self.fixed_routes]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate fixed route ids: {dupes}")
        flags = [r.when.flag for r in self.fixed_routes if isinstance(r.when, GuardrailFlagTrigger)]
        dup_flags = sorted({f for f in flags if flags.count(f) > 1})
        if dup_flags:
            raise ValueError(f"more than one fixed route for guardrail flags: {dup_flags}")
        return self

    def referenced_agent_ids(self) -> List[str]:
        """Every agent id this config names, for validation against the registry."""
        out = [self.default_agent]
        for r in self.fixed_routes:
            if r.agent_id not in out:
                out.append(r.agent_id)
        return out


class RouteSource(str, Enum):
    """How the agent(s) for a turn were chosen."""

    MAIN_AGENT = "main_agent"
    FIXED_ROUTE = "fixed_route"
    USER_SELECTED = "user_selected"
    DEFAULT_AGENT = "default_agent"


FallbackReason = Literal["model_unavailable", "main_agent_failed"]


class RouteDecision(_Strict):
    """How a turn was routed, including any fallback.

    Not persisted on its own: it travels as the ``route`` entry of the audit
    payload on ``route.*`` events (``to_audit_payload``).
    """

    source: RouteSource
    route_id: Optional[str] = Field(default=None, pattern=ROUTE_ID_PATTERN)
    agent_id: Optional[str] = Field(default=None, description="Agent that received the turn, when known.")
    fallback_reason: Optional[FallbackReason] = None

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _check_agent_id(v)

    @model_validator(mode="after")
    def _check(self) -> RouteDecision:
        if (self.source == RouteSource.FIXED_ROUTE) != (self.route_id is not None):
            raise ValueError("route_id is required for, and only for, fixed_route decisions")
        if (self.source == RouteSource.DEFAULT_AGENT) != (self.fallback_reason is not None):
            raise ValueError("fallback_reason is required for, and only for, default_agent decisions")
        return self

    def to_audit_payload(self) -> Dict[str, Any]:
        """Returns the ``payload`` dict for a ``route.*`` audit event."""
        return {"route": self.model_dump(mode="json", exclude_none=True)}


# ---------------------------------------------------------------------------
# Stream status events
# ---------------------------------------------------------------------------

NoticeCode = Literal["model_unavailable", "main_agent_failed", "partial_failure", "truncated"]

TaskState = Literal["started", "completed", "failed", "timed_out", "cancelled"]


class SSETaskStatusEvent(_Strict):
    """Status change of one subagent task (one ``task`` tool call).

    ``task_id`` is the id of the tool call that started the subagent. Subagent
    tokens are never streamed; only status changes are.
    """

    type: Literal["task_status"] = "task_status"
    turn_id: str
    task_id: str = Field(..., min_length=1)
    agent_id: str
    state: TaskState
    detail: Optional[str] = Field(default=None, description="Short user-safe detail, e.g. a timeout note.")

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)


class SSEOrchestrationNoticeEvent(_Strict):
    """User-visible notice about a fallback or degraded turn."""

    type: Literal["orchestration_notice"] = "orchestration_notice"
    turn_id: str
    code: NoticeCode
    message: str = Field(..., min_length=1)
    agent_ids: List[str] = Field(default_factory=list, description="Agents the notice concerns.")

    @field_validator("agent_ids")
    @classmethod
    def _check_ids(cls, v: List[str]) -> List[str]:
        return [_check_agent_id(a) for a in v]


OrchestrationStreamEvent = Annotated[
    Union[SSETaskStatusEvent, SSEOrchestrationNoticeEvent],
    Field(discriminator="type"),
]


__all__ = [
    "DEFAULT_AGENT_TIMEOUT_S",
    "DEFAULT_MAX_AGENTS",
    "DEFAULT_TURN_TIMEOUT_S",
    "FallbackReason",
    "FixedRoute",
    "GuardrailFlagTrigger",
    "HasAttachmentsTrigger",
    "NoticeCode",
    "ORCHESTRATION_SCHEMA_VERSION",
    "OrchestrationLimits",
    "OrchestrationStreamEvent",
    "PackOrchestrationSpec",
    "ROUTE_ID_PATTERN",
    "RouteDecision",
    "RouteSource",
    "RouteTrigger",
    "SSEOrchestrationNoticeEvent",
    "SSETaskStatusEvent",
    "TaskState",
]
