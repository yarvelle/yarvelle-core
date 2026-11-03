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

"""Typed, versioned data contracts for dynamic multi-agent orchestration.

These schemas describe the data that flows through one orchestrated turn:

- ``OrchestrationPlan``: the structured plan a planner returns (mode, steps,
  agent ids, ordering, rationale, clarification request).
- ``AgentTaskEnvelope`` / ``AgentTaskResult``: what each agent is handed and
  what it returns, with a closed status set and provenance.
- ``OrchestrationLimits``: fan-out and timeout bounds, overridable per pack.
- ``PackOrchestrationSpec``: pack-declared default agent and fixed routes.
- Stream status events emitted during multi-agent turns.
- ``OrchestrationAuditRecord``: per-hand-off audit shapes with a durability
  class per event type.

The module is data-only. Agent ids are opaque slugs supplied by packs; core
never names a specific agent here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yarvelle_core.schemas.a2a import A2AArtifact, A2AMessage
from yarvelle_core.schemas.manifest import SLUG_REGEX
from yarvelle_core.schemas.plan import ExecutionMode

ORCHESTRATION_SCHEMA_VERSION: Literal[1] = 1
"""Current version of every versioned contract in this module."""

STEP_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"
SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"

DEFAULT_MAX_AGENTS = 4
DEFAULT_AGENT_TIMEOUT_S = 60.0
DEFAULT_TURN_TIMEOUT_S = 120.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _check_agent_id(v: str) -> str:
    if not v or not SLUG_REGEX.match(v):
        raise ValueError(f"Invalid agent id '{v}': must match {SLUG_REGEX.pattern}")
    return v


def _check_aware(v: Optional[datetime]) -> Optional[datetime]:
    if v is not None and v.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return v


def content_sha256(body: str) -> str:
    """Returns the SHA-256 hex digest of a UTF-8 text body (audit and provenance hashes)."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


class OrchestrationLimits(_Strict):
    """Per-turn bounds on fan-out and wall-clock time."""

    max_agents: int = Field(
        default=DEFAULT_MAX_AGENTS,
        ge=1,
        le=16,
        description="Maximum number of agent steps in one plan.",
    )
    agent_timeout_s: float = Field(
        default=DEFAULT_AGENT_TIMEOUT_S,
        gt=0,
        description="Wall-clock timeout for a single agent task, in seconds.",
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
# Plan
# ---------------------------------------------------------------------------


class PlanStep(_Strict):
    """One agent assignment inside an orchestration plan."""

    step_id: str = Field(..., pattern=STEP_ID_PATTERN, description="Plan-local step identifier.")
    agent_id: str = Field(..., description="Registered agent responsible for this step.")
    instructions: str = Field(default="", description="Focused instructions for the agent.")
    depends_on: List[str] = Field(
        default_factory=list,
        description="Step ids whose outputs this step consumes (pipeline mode only).",
    )

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)


class OrchestrationPlan(_Strict):
    """Structured plan for one user turn.

    Invariants:
    - A plan either asks for clarification (no steps, a question) or has steps.
    - ``single`` has exactly one step; ``parallel`` and ``deliberate`` have two
      or more independent steps; ``pipeline`` has two or more steps forming an
      acyclic dependency graph.
    - Step ids are unique and every dependency names an existing step.
    """

    schema_version: Literal[1] = ORCHESTRATION_SCHEMA_VERSION
    plan_id: str = Field(default_factory=_new_id)
    mode: ExecutionMode
    steps: List[PlanStep] = Field(default_factory=list)
    panel_id: Optional[str] = Field(
        default=None,
        pattern=STEP_ID_PATTERN,
        description="Pack-declared panel, deliberate mode only.",
    )
    rationale: str = Field(default="", description="Why this mode and these agents were chosen.")
    needs_clarification: bool = Field(default=False)
    clarification_question: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def _check_plan(self) -> OrchestrationPlan:
        if self.needs_clarification:
            if not (self.clarification_question and self.clarification_question.strip()):
                raise ValueError("clarification_question is required when needs_clarification is true")
            if self.steps:
                raise ValueError("a plan that needs clarification must not contain steps")
            return self
        if self.clarification_question is not None:
            raise ValueError("clarification_question is only allowed when needs_clarification is true")
        if not self.steps:
            raise ValueError("plan must contain at least one step")

        ids = [s.step_id for s in self.steps]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate step ids: {dupes}")
        known = set(ids)
        for step in self.steps:
            for dep in step.depends_on:
                if dep == step.step_id:
                    raise ValueError(f"step '{step.step_id}' depends on itself")
                if dep not in known:
                    raise ValueError(f"step '{step.step_id}' depends on unknown step '{dep}'")

        has_deps = any(s.depends_on for s in self.steps)
        n = len(self.steps)
        if self.mode == ExecutionMode.SINGLE and n != 1:
            raise ValueError("single mode requires exactly one step")
        if self.mode in (ExecutionMode.PARALLEL, ExecutionMode.PIPELINE, ExecutionMode.DELIBERATE) and n < 2:
            raise ValueError(f"{self.mode.value} mode requires at least two steps")
        if self.mode != ExecutionMode.PIPELINE and has_deps:
            raise ValueError(f"depends_on is only allowed in pipeline mode, not {self.mode.value}")
        if self.mode == ExecutionMode.PIPELINE and not has_deps:
            raise ValueError("pipeline mode requires at least one dependency between steps")
        if self.mode == ExecutionMode.DELIBERATE:
            agents = [s.agent_id for s in self.steps]
            if len(set(agents)) != len(agents):
                raise ValueError("deliberate mode requires distinct agents")
        elif self.panel_id is not None:
            raise ValueError("panel_id is only allowed in deliberate mode")

        self.execution_order()  # raises on cycles
        return self

    def execution_order(self) -> List[List[str]]:
        """Returns step ids grouped into waves; each wave depends only on earlier waves.

        Order inside a wave follows the declared step order, so the result is
        deterministic. Raises ``ValueError`` if the dependencies contain a cycle.
        """
        remaining = {s.step_id: set(s.depends_on) for s in self.steps}
        declared = [s.step_id for s in self.steps]
        done: set[str] = set()
        waves: List[List[str]] = []
        while remaining:
            wave = [sid for sid in declared if sid in remaining and remaining[sid] <= done]
            if not wave:
                raise ValueError(f"dependency cycle among steps: {sorted(remaining)}")
            waves.append(wave)
            done.update(wave)
            for sid in wave:
                del remaining[sid]
        return waves

    def agent_ids(self) -> List[str]:
        """Distinct agent ids referenced by the plan, in declared order."""
        seen: List[str] = []
        for s in self.steps:
            if s.agent_id not in seen:
                seen.append(s.agent_id)
        return seen

    def limit_violations(self, limits: OrchestrationLimits) -> List[str]:
        """Lists the ways this plan exceeds ``limits`` (empty when within bounds)."""
        errors: List[str] = []
        if len(self.steps) > limits.max_agents:
            errors.append(f"plan has {len(self.steps)} steps; the limit is {limits.max_agents}")
        return errors


# ---------------------------------------------------------------------------
# Task envelopes and results
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Terminal outcome of one agent task."""

    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class AgentTaskEnvelope(_Strict):
    """Everything one agent is handed for one plan step."""

    schema_version: Literal[1] = ORCHESTRATION_SCHEMA_VERSION
    task_id: str = Field(default_factory=_new_id)
    parent_task_id: Optional[str] = Field(default=None, description="Task that spawned this one, if any.")
    turn_id: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    step_id: str = Field(..., pattern=STEP_ID_PATTERN)
    agent_id: str
    message: A2AMessage = Field(..., description="Hand-off message carrying instructions and inputs.")
    upstream_task_ids: List[str] = Field(
        default_factory=list,
        description="Completed tasks whose outputs are included as read-only context.",
    )
    timeout_s: float = Field(default=DEFAULT_AGENT_TIMEOUT_S, gt=0)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)
    @field_validator("created_at")
    @classmethod
    def _validate_ts(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _check_aware(v)

    @model_validator(mode="after")
    def _check_message(self) -> AgentTaskEnvelope:
        if self.message.role != "user":
            raise ValueError("hand-off message role must be 'user'")
        if self.message.task_id is not None and self.message.task_id != self.task_id:
            raise ValueError("hand-off message task_id must match the envelope task_id")
        if self.task_id in self.upstream_task_ids:
            raise ValueError("a task cannot list itself as upstream")
        return self


class TaskProvenance(_Strict):
    """Where a task result came from, for attribution and audit."""

    agent_id: str
    plan_id: str = Field(..., min_length=1)
    step_id: str = Field(..., pattern=STEP_ID_PATTERN)
    turn_id: str = Field(..., min_length=1)
    model: Optional[str] = Field(default=None, description="Provider/model identifier that produced the output.")
    agent_version: Optional[str] = None
    input_hash: Optional[str] = Field(
        default=None,
        pattern=SHA256_HEX_PATTERN,
        description="SHA-256 of the canonical hand-off input; absent only for skipped tasks.",
    )
    output_hash: Optional[str] = Field(default=None, pattern=SHA256_HEX_PATTERN)
    upstream_task_ids: List[str] = Field(default_factory=list)

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, v: str) -> str:
        return _check_agent_id(v)


class AgentTaskResult(_Strict):
    """Typed outcome of one agent task.

    - ``completed``: ``output_text`` and ``provenance.output_hash`` are set; no error.
    - ``failed`` / ``timed_out``: ``error_code`` is set; no output.
    - ``skipped``: ``skip_reason`` is set; the task never started, so no output or timings.
    """

    schema_version: Literal[1] = ORCHESTRATION_SCHEMA_VERSION
    task_id: str = Field(..., min_length=1)
    status: TaskStatus
    output_text: Optional[str] = None
    artifacts: List[A2AArtifact] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_.-]{1,64}$")
    error_message: Optional[str] = Field(default=None, description="Redacted, user-safe error description.")
    skip_reason: Optional[str] = None
    truncated: bool = Field(default=False, description="True when the tool-loop cap cut the run short.")
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    provenance: TaskProvenance

    @field_validator("started_at", "ended_at")
    @classmethod
    def _validate_ts(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _check_aware(v)

    @model_validator(mode="after")
    def _check_status(self) -> AgentTaskResult:
        has_output = self.output_text is not None or bool(self.artifacts)
        if self.status == TaskStatus.COMPLETED:
            if self.output_text is None:
                raise ValueError("completed results require output_text")
            if self.error_code or self.skip_reason:
                raise ValueError("completed results cannot carry error_code or skip_reason")
            if self.provenance.output_hash != content_sha256(self.output_text):
                raise ValueError("provenance.output_hash must be the SHA-256 of output_text")
        elif self.status in (TaskStatus.FAILED, TaskStatus.TIMED_OUT):
            if not self.error_code:
                raise ValueError(f"{self.status.value} results require error_code")
            if has_output or self.skip_reason:
                raise ValueError(f"{self.status.value} results cannot carry output or skip_reason")
        else:
            if not (self.skip_reason and self.skip_reason.strip()):
                raise ValueError("skipped results require skip_reason")
            if has_output or self.error_code or self.started_at or self.ended_at:
                raise ValueError("skipped results cannot carry output, error_code or timings")
        if self.status != TaskStatus.SKIPPED and self.provenance.input_hash is None:
            raise ValueError("tasks that ran require provenance.input_hash")
        if self.status != TaskStatus.COMPLETED and self.provenance.output_hash is not None:
            raise ValueError("only completed results carry provenance.output_hash")
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        return self

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at is None or self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000.0


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
    flag: str = Field(..., pattern=STEP_ID_PATTERN)


RouteTrigger = Annotated[Union[HasAttachmentsTrigger, GuardrailFlagTrigger], Field(discriminator="kind")]


class FixedRoute(_Strict):
    """A pack-declared deterministic route, evaluated before planning in declared order."""

    route_id: str = Field(..., pattern=STEP_ID_PATTERN)
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
    routes) and when planning fails; both cases carry a user-visible notice.
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

    PLANNER = "planner"
    FIXED_ROUTE = "fixed_route"
    USER_SELECTED = "user_selected"
    DEFAULT_AGENT = "default_agent"


class RouteDecision(_Strict):
    """Record of how a turn was routed, including any fallback."""

    source: RouteSource
    route_id: Optional[str] = Field(default=None, pattern=STEP_ID_PATTERN)
    fallback_reason: Optional[Literal["planner_unavailable", "planning_failed"]] = None

    @model_validator(mode="after")
    def _check(self) -> RouteDecision:
        if (self.source == RouteSource.FIXED_ROUTE) != (self.route_id is not None):
            raise ValueError("route_id is required for, and only for, fixed_route decisions")
        if (self.source == RouteSource.DEFAULT_AGENT) != (self.fallback_reason is not None):
            raise ValueError("fallback_reason is required for, and only for, default_agent decisions")
        return self


# ---------------------------------------------------------------------------
# Stream status events
# ---------------------------------------------------------------------------

NoticeCode = Literal["planner_unavailable", "planning_failed", "partial_failure", "truncated"]


class SSEOrchestrationPlanEvent(_Strict):
    """Announces the chosen plan before agents run."""

    type: Literal["orchestration_plan"] = "orchestration_plan"
    turn_id: str
    plan_id: str
    mode: ExecutionMode
    steps: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Ordered {'step_id', 'agent_id'} pairs; instructions are not streamed.",
    )

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, v: List[Dict[str, str]]) -> List[Dict[str, str]]:
        for item in v:
            if set(item) != {"step_id", "agent_id"}:
                raise ValueError("each step must have exactly 'step_id' and 'agent_id'")
            _check_agent_id(item["agent_id"])
        return v

    @classmethod
    def from_plan(cls, plan: OrchestrationPlan, turn_id: str) -> SSEOrchestrationPlanEvent:
        return cls(
            turn_id=turn_id,
            plan_id=plan.plan_id,
            mode=plan.mode,
            steps=[{"step_id": s.step_id, "agent_id": s.agent_id} for s in plan.steps],
        )


class SSETaskStatusEvent(_Strict):
    """Status change of one agent task. Agent tokens are never streamed in multi-agent turns."""

    type: Literal["task_status"] = "task_status"
    turn_id: str
    task_id: str
    step_id: str = Field(..., pattern=STEP_ID_PATTERN)
    agent_id: str
    state: Literal["started", "completed", "failed", "timed_out", "skipped"]
    detail: Optional[str] = Field(default=None, description="Short user-safe detail, e.g. a skip reason.")

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
    Union[SSEOrchestrationPlanEvent, SSETaskStatusEvent, SSEOrchestrationNoticeEvent],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

OrchestrationAuditEventType = Literal[
    "plan.created",
    "plan.rejected",
    "plan.fallback",
    "route.fixed",
    "task.started",
    "task.completed",
    "task.failed",
    "task.timed_out",
    "task.skipped",
    "tool.called",
    "synthesis.completed",
    "telemetry.stream",
]

AuditDurability = Literal["strict", "best_effort"]

_BEST_EFFORT_PREFIXES = ("telemetry.",)


def audit_durability(event: str) -> AuditDurability:
    """Returns how an audit write must be treated.

    ``strict`` events (plan, route, task, tool, synthesis) must be recorded
    before the turn continues; a failed write stops the turn. ``best_effort``
    events (telemetry) may be dropped on failure.
    """
    return "best_effort" if event.startswith(_BEST_EFFORT_PREFIXES) else "strict"


class OrchestrationAuditRecord(_Strict):
    """One audit record for a plan, route, hand-off, tool call or synthesis step.

    Hashes are always present when a body exists; bodies themselves are kept
    only when the deployment stores audit bodies (see ``without_bodies``).
    """

    schema_version: Literal[1] = ORCHESTRATION_SCHEMA_VERSION
    event: OrchestrationAuditEventType
    ts: datetime = Field(default_factory=_utc_now)
    thread_id: str = Field(..., min_length=1)
    turn_id: str = Field(..., min_length=1)
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    agent_id: Optional[str] = None
    tool: Optional[str] = None
    input_hash: Optional[str] = Field(default=None, pattern=SHA256_HEX_PATTERN)
    output_hash: Optional[str] = Field(default=None, pattern=SHA256_HEX_PATTERN)
    input_body: Optional[str] = None
    output_body: Optional[str] = None
    error_code: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_.-]{1,64}$")
    duration_ms: Optional[float] = Field(default=None, ge=0)
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-specific, already-redacted fields.")

    @field_validator("ts")
    @classmethod
    def _validate_ts(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _check_aware(v)

    @field_validator("agent_id")
    @classmethod
    def _check_agent(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _check_agent_id(v)

    @model_validator(mode="after")
    def _check_record(self) -> OrchestrationAuditRecord:
        if self.event.startswith("task.") and not (self.task_id and self.agent_id):
            raise ValueError(f"{self.event} events require task_id and agent_id")
        if self.event.startswith("plan.") and not self.plan_id:
            raise ValueError(f"{self.event} events require plan_id")
        if self.event == "tool.called" and not (self.tool and self.task_id):
            raise ValueError("tool.called events require tool and task_id")
        for body, digest, name in (
            (self.input_body, self.input_hash, "input"),
            (self.output_body, self.output_hash, "output"),
        ):
            if body is not None and digest != content_sha256(body):
                raise ValueError(f"{name}_hash must be the SHA-256 of {name}_body")
        return self

    @property
    def durability(self) -> AuditDurability:
        return audit_durability(self.event)

    def without_bodies(self) -> OrchestrationAuditRecord:
        """Copy with bodies removed and hashes kept, for deployments that do not store bodies."""
        return self.model_copy(update={"input_body": None, "output_body": None})


__all__ = [
    "AgentTaskEnvelope",
    "AgentTaskResult",
    "AuditDurability",
    "DEFAULT_AGENT_TIMEOUT_S",
    "DEFAULT_MAX_AGENTS",
    "DEFAULT_TURN_TIMEOUT_S",
    "FixedRoute",
    "GuardrailFlagTrigger",
    "HasAttachmentsTrigger",
    "NoticeCode",
    "ORCHESTRATION_SCHEMA_VERSION",
    "OrchestrationAuditEventType",
    "OrchestrationAuditRecord",
    "OrchestrationLimits",
    "OrchestrationPlan",
    "OrchestrationStreamEvent",
    "PackOrchestrationSpec",
    "PlanStep",
    "RouteDecision",
    "RouteSource",
    "RouteTrigger",
    "SSEOrchestrationNoticeEvent",
    "SSEOrchestrationPlanEvent",
    "SSETaskStatusEvent",
    "TaskProvenance",
    "TaskStatus",
    "audit_durability",
    "content_sha256",
]
