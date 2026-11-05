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

"""Hybrid turn routing and the main Deep Agents agent.

Order of decisions for a turn:

1. a user-selected agent, when it is registered;
2. the first pack fixed route that fires (``routing.select_fixed_route``);
3. without a model: the pack ``default_agent``, with a ``model_unavailable``
   notice (core never substitutes a mock or a keyword guess);
4. otherwise the main agent, which hands work to registered subagents through
   the Deep Agents ``task`` tool, guarded by ``TaskGuardMiddleware``.

The main agent is assembled from the Deep Agents ``SubAgentMiddleware`` only,
so it gets the ``task`` tool and nothing else: no general-purpose subagent and
no filesystem tools. Hidden agents are never offered.
"""

from __future__ import annotations

import asyncio

import logging
import uuid
from dataclasses import dataclass, field
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Union

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.engine.orchestration.routing import select_fixed_route
from yarvelle_core.engine.orchestration.task_guard import (
    TASK_TOOL_NAME,
    AuditSink,
    OrchestrationAuditError,
    SubagentCallCapMiddleware,
    TaskGuardMiddleware,
    TaskRun,
    TaskStatusSink,
    _emit,
)
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import (
    OrchestrationLimits,
    PackOrchestrationSpec,
    RejectedPickReason,
    RouteDecision,
    RouteSource,
    SSEOrchestrationNoticeEvent,
    SynthesisSpec,
    TaskProvenance,
    TurnTaskRecord,
)

logger = logging.getLogger(__name__)

MAIN_AGENT_ID = "main-agent"

MAIN_AGENT_PROMPT = (
    "You coordinate a team of specialist agents. Answer directly when no "
    "specialist is needed. Otherwise hand each part of the request to the best "
    "matching agent with the task tool, then combine their answers into one "
    "reply. Use only the listed agents. If an agent fails, times out or stops "
    "early, say in the reply which part is missing. Refer to agents by their "
    "titles, never by their ids."
)

_TERMINAL_EVENTS = {
    "task.completed": "completed",
    "task.failed": "failed",
    "task.timed_out": "timed_out",
    "task.cancelled": "cancelled",
}

ToolResolver = Callable[[str, List[str]], List[Any]]
"""Maps (agent_id, declared tool names) to runnable tools for that subagent."""

TurnTaskSink = Callable[[List[TurnTaskRecord]], Union[None, Awaitable[None]]]
"""Stores the hand-off records of one turn (``turn_tasks``). A failure stops the turn."""

_NOTICE_TEXT = {
    "model_unavailable": "No model is configured, so the default agent took this turn.",
    "main_agent_failed": "The coordinating agent failed, so the default agent took this turn.",
}


@dataclass
class TurnOutcome:
    """Result of routing (and, for the main agent, running) one turn."""

    decision: RouteDecision
    turn_id: str
    messages: List[BaseMessage] = field(default_factory=list)
    notices: List[SSEOrchestrationNoticeEvent] = field(default_factory=list)
    tasks_started: int = 0
    tasks: List[TaskRun] = field(default_factory=list)
    provenance: List[TaskProvenance] = field(default_factory=list)


def compose_main_prompt(base: Optional[str] = None, synthesis: Optional[SynthesisSpec] = None) -> str:
    """Main agent system prompt: the base prompt plus the pack's synthesis instructions."""
    prompt = base or MAIN_AGENT_PROMPT
    extra = (synthesis.instructions if synthesis is not None else "").strip()
    if not extra:
        return prompt
    return f"{prompt}\n\nHow to compose the reply:\n{extra}"


def build_provenance(
    runs: Sequence[TaskRun],
    audit_records: Sequence[AuditEvent],
    titles: Mapping[str, str],
) -> List[TaskProvenance]:
    """One entry per hand-off, in request order, from the turn's audit records.

    The terminal ``task.*`` record decides the state and carries the output
    hash; the run supplies the truncation flag and the reporting agent name.
    """
    terminal: Dict[str, AuditEvent] = {}
    for record in audit_records:
        if record.task_id and record.event in _TERMINAL_EVENTS:
            terminal[str(record.task_id)] = record
    out: List[TaskProvenance] = []
    for run in runs:
        record = terminal.get(run.task_id)
        state = _TERMINAL_EVENTS[record.event] if record is not None else run.state
        out.append(
            TaskProvenance(
                task_id=run.task_id,
                agent_id=run.agent_id,
                agent_title=titles.get(run.agent_id) or run.agent_id,
                state=state,  # type: ignore[arg-type]
                truncated=run.truncated,
                output_hash=getattr(record, "output_hash", None) if record is not None else None,
                verified=run.lc_agent_name == run.agent_id,
            )
        )
    return out


def build_turn_tasks(
    audit_records: Sequence[AuditEvent],
    runs: Sequence[TaskRun],
    titles: Mapping[str, str],
    *,
    turn_id: str,
    thread_id: Optional[str] = None,
) -> List[TurnTaskRecord]:
    """One stored record per hand-off of the turn, in request order.

    Hand-offs refused before they started (policy or limits) are included with
    their ``task.failed`` record, so the table matches the audit log.
    """
    run_by_id = {run.task_id: run for run in runs}
    order: List[str] = []
    started: Dict[str, AuditEvent] = {}
    terminal: Dict[str, AuditEvent] = {}
    for record in audit_records:
        task_id = str(record.task_id or "")
        if not task_id or not record.event.startswith("task."):
            continue
        if task_id not in order:
            order.append(task_id)
        if record.event == "task.started":
            started[task_id] = record
        elif record.event in _TERMINAL_EVENTS:
            terminal[task_id] = record
    out: List[TurnTaskRecord] = []
    for task_id in order:
        first = started.get(task_id) or terminal[task_id]
        end = terminal.get(task_id)
        run = run_by_id.get(task_id)
        agent_id = run.agent_id if run is not None else str(first.agent_id)
        out.append(
            TurnTaskRecord(
                turn_id=turn_id,
                task_id=task_id,
                thread_id=thread_id,
                parent_task_id=first.parent_task_id,
                agent_id=agent_id,
                agent_title=titles.get(agent_id) or agent_id,
                state=_TERMINAL_EVENTS[end.event] if end is not None else "started",  # type: ignore[arg-type]
                truncated=run.truncated if run is not None else False,
                verified=run is not None and run.lc_agent_name == run.agent_id,
                input_hash=first.input_hash,
                output_hash=end.output_hash if end is not None else None,
                error_code=end.error_code if end is not None else None,
                started_at=started[task_id].ts if task_id in started else None,
                duration_ms=int(round(end.duration_ms)) if end is not None and end.duration_ms is not None else None,
            )
        )
    return out


async def store_turn_tasks(sink: Optional[TurnTaskSink], rows: List[TurnTaskRecord]) -> None:
    """Sends the turn's hand-off records to ``sink``; a failed write stops the turn."""
    if sink is None or not rows:
        return
    try:
        result = sink(rows)
        if inspect.isawaitable(result):
            await result
    except Exception as err:
        raise OrchestrationAuditError("could not store the turn's hand-off records") from err


_ROUTE_EVENTS = {
    RouteSource.USER_SELECTED: "route.user_selected",
    RouteSource.FIXED_ROUTE: "route.fixed",
    RouteSource.DEFAULT_AGENT: "route.default",
    RouteSource.MAIN_AGENT: "route.main_agent",
    RouteSource.MODEL_CLASSIFIED: "route.classified",
}


def route_event(decision: RouteDecision, turn_id: str, thread_id: Optional[str] = None) -> AuditEvent:
    """The ``route.*`` audit record for one routing decision."""
    return AuditEvent(
        event=_ROUTE_EVENTS[decision.source],  # type: ignore[arg-type]
        agent_id=decision.agent_id or MAIN_AGENT_ID,
        turn_id=turn_id,
        thread_id=thread_id,
        details=decision.to_audit_payload(),
    )


async def record_route(
    sink: Optional[AuditSink],
    decision: RouteDecision,
    turn_id: str,
    thread_id: Optional[str] = None,
) -> None:
    """Sends the decision's ``route.*`` record to ``sink``; a failed write stops the turn."""
    if sink is None:
        return
    record = route_event(decision, turn_id, thread_id)
    try:
        await _emit(sink, record)
    except Exception as err:
        raise OrchestrationAuditError(f"could not record {record.event}") from err


def pick_rejection(registry: Optional[AgentRegistry], agent_id: Optional[str]) -> Optional[RejectedPickReason]:
    """Why ``agent_id`` may not be picked directly, or None when it may.

    Hidden agents (system agents and any agent marked ``hidden``) only run when
    routing sends work to them; a caller can never pick one. With no registry
    to check against, nothing is refused here.
    """
    if not agent_id or registry is None:
        return None
    manifest = registry.get(agent_id)
    if manifest is None:
        return "unknown"
    if getattr(manifest, "hidden", False):
        return "hidden"
    return None


def rejected_pick_event(
    agent_id: str,
    reason: RejectedPickReason,
    turn_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> AuditEvent:
    """The ``route.rejected`` audit record for a refused agent pick."""
    return AuditEvent(
        event="route.rejected",
        agent_id=agent_id,
        allowed=False,
        reason=f"agent_pick_{reason}",
        turn_id=turn_id,
        thread_id=thread_id,
        details={"rejected_pick": {"agent_id": agent_id, "reason": reason}},
    )


async def record_rejected_pick(
    sink: Optional[AuditSink],
    agent_id: str,
    reason: RejectedPickReason,
    turn_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    """Sends the ``route.rejected`` record to ``sink``; a failed write stops the turn."""
    if sink is None:
        return
    record = rejected_pick_event(agent_id, reason, turn_id, thread_id)
    try:
        await _emit(sink, record)
    except Exception as err:
        raise OrchestrationAuditError(f"could not record {record.event}") from err


def _join(titles: Sequence[str]) -> str:
    if len(titles) <= 2:
        return " and ".join(titles)
    return ", ".join(titles[:-1]) + f" and {titles[-1]}"


_GAP_STATES = ("failed", "timed_out", "cancelled")


def gap_statement(provenance: Sequence[TaskProvenance]) -> Optional[str]:
    """Plain sentence naming agents that did not answer or stopped early."""
    missing = list(dict.fromkeys(p.agent_title for p in provenance if p.state in _GAP_STATES))
    truncated = list(dict.fromkeys(p.agent_title for p in provenance if p.truncated and p.agent_title not in missing))
    parts: List[str] = []
    if missing:
        parts.append(f"{_join(missing)} did not answer, so that part is missing from this reply.")
    if truncated:
        parts.append(f"{_join(truncated)} stopped early at the call limit, so that part may be incomplete.")
    return " ".join(parts) or None


def state_gaps(messages: List[BaseMessage], provenance: Sequence[TaskProvenance]) -> List[BaseMessage]:
    """Makes sure the final answer names every missing or truncated agent.

    The main agent is asked to do this itself; when its answer does not name
    an affected agent, the gap sentence is appended to that answer.
    """
    statement = gap_statement(provenance)
    if statement is None:
        return messages
    answer = final_answer(messages)
    if answer is None:
        return [*messages, AIMessage(content=statement)]
    text = answer.content if isinstance(answer.content, str) else str(answer.content)
    affected = {p.agent_title for p in provenance if p.truncated or p.state in _GAP_STATES}
    if all(title.lower() in text.lower() for title in affected):
        return messages
    content = f"{text.rstrip()}\n\n{statement}" if text.strip() else statement
    updated = answer.model_copy(update={"content": content})
    return [updated if m is answer else m for m in messages]


def task_notices(turn_id: str, runs: Sequence[TaskRun]) -> List[SSEOrchestrationNoticeEvent]:
    """Notices for hand-offs that failed, timed out or hit their call cap."""
    notices: List[SSEOrchestrationNoticeEvent] = []
    missing = sorted({r.agent_id for r in runs if r.state in ("failed", "timed_out")})
    if missing:
        count = len(missing)
        notices.append(
            SSEOrchestrationNoticeEvent(
                turn_id=turn_id,
                code="partial_failure",
                message=f"{count} agent{'s' if count > 1 else ''} did not answer, so this reply may be incomplete.",
                agent_ids=missing,
            )
        )
    truncated = sorted({r.agent_id for r in runs if r.truncated})
    if truncated:
        count = len(truncated)
        notices.append(
            SSEOrchestrationNoticeEvent(
                turn_id=turn_id,
                code="truncated",
                message=f"{count} agent{'s' if count > 1 else ''} stopped at the call limit, so this reply may be incomplete.",
                agent_ids=truncated,
            )
        )
    return notices


def _subagent_specs(
    registry: AgentRegistry,
    model: BaseChatModel,
    tool_resolver: Optional[ToolResolver],
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for spec in registry.list_subagents():
        tools = list(spec.get("tools") or [])
        if any(isinstance(t, str) for t in tools):
            names = [t for t in tools if isinstance(t, str)]
            if tool_resolver is not None:
                tools = [t for t in tools if not isinstance(t, str)] + list(tool_resolver(spec["name"], names))
            else:
                logger.warning("No tool resolver: subagent %s runs without its declared tools", spec["name"])
                tools = [t for t in tools if not isinstance(t, str)]
        spec = dict(spec)
        spec["tools"] = tools
        spec.setdefault("model", model)
        manifest = registry.get(spec["name"])
        cap = SubagentCallCapMiddleware(spec["name"], getattr(manifest, "max_iterations", None))
        spec["middleware"] = [*list(spec.get("middleware") or []), cap]
        specs.append(spec)
    return specs


def build_main_agent(
    model: BaseChatModel,
    registry: AgentRegistry,
    guard: TaskGuardMiddleware,
    *,
    system_prompt: Optional[str] = None,
    tool_resolver: Optional[ToolResolver] = None,
    checkpointer: Any = None,
) -> Any:
    """Compiles the main agent: the ``task`` tool over registry subagents, guarded."""
    from deepagents.backends import StateBackend
    from deepagents.middleware.subagents import SubAgentMiddleware

    specs = _subagent_specs(registry, model, tool_resolver)
    if not specs:
        raise ValueError("the registry offers no subagents to the main agent")
    limits = guard.limits
    middleware = [
        SubAgentMiddleware(backend=StateBackend(), subagents=specs),
        guard,
        ToolCallLimitMiddleware(tool_name=TASK_TOOL_NAME, run_limit=limits.max_agents, exit_behavior="continue"),
        # Each hand-off needs a model turn to request it, plus one to answer.
        ModelCallLimitMiddleware(run_limit=limits.max_agents + 2, exit_behavior="end"),
    ]
    return create_agent(
        model,
        tools=[],
        system_prompt=system_prompt or compose_main_prompt(),
        middleware=middleware,
        checkpointer=checkpointer,
        name=MAIN_AGENT_ID,
    )


class HybridRouter:
    """Routes a turn: user choice, fixed routes, default agent, or the main agent."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        model: Optional[BaseChatModel],
        spec: Optional[PackOrchestrationSpec] = None,
        default_agent: Optional[str] = None,
        audit_sink: Optional[AuditSink] = None,
        status_sink: Optional[TaskStatusSink] = None,
        system_prompt: Optional[str] = None,
        tool_resolver: Optional[ToolResolver] = None,
        task_sink: Optional[TurnTaskSink] = None,
    ) -> None:
        self.registry = registry
        self.task_sink = task_sink
        self.model = model
        self.spec = spec
        self.default_agent = (spec.default_agent if spec is not None else None) or default_agent
        self.audit_sink = audit_sink
        self.status_sink = status_sink
        self.system_prompt = compose_main_prompt(system_prompt, spec.synthesis if spec is not None else None)
        self.tool_resolver = tool_resolver

    @property
    def limits(self) -> OrchestrationLimits:
        return self.spec.limits if self.spec is not None else OrchestrationLimits()

    def _is_visible(self, agent_id: str) -> bool:
        manifest = self.registry.get(agent_id)
        return manifest is not None and not getattr(manifest, "hidden", False)

    def _default_decision(self, reason: str) -> Optional[RouteDecision]:
        if not self.default_agent:
            return None
        return RouteDecision(source=RouteSource.DEFAULT_AGENT, agent_id=self.default_agent, fallback_reason=reason)  # type: ignore[arg-type]

    def decide(self, state: Mapping[str, Any], explicit_agent: Optional[str] = None) -> Optional[RouteDecision]:
        """Returns how this turn is routed, or None when nothing can take it."""
        if explicit_agent and self._is_visible(explicit_agent):
            return RouteDecision(source=RouteSource.USER_SELECTED, agent_id=explicit_agent)
        fixed = select_fixed_route(self.spec, state)
        if fixed is not None:
            return fixed
        if self.model is None:
            return self._default_decision("model_unavailable")
        return RouteDecision(source=RouteSource.MAIN_AGENT)

    def notice_for(self, decision: RouteDecision, turn_id: str) -> Optional[SSEOrchestrationNoticeEvent]:
        if decision.fallback_reason is None:
            return None
        return SSEOrchestrationNoticeEvent(
            turn_id=turn_id,
            code=decision.fallback_reason,
            message=_NOTICE_TEXT[decision.fallback_reason],
            agent_ids=[decision.agent_id] if decision.agent_id else [],
        )

    async def audit_route(self, decision: RouteDecision, turn_id: str, thread_id: Optional[str] = None) -> None:
        """Records the ``route.*`` event for a decision (strict durability)."""
        await record_route(self.audit_sink, decision, turn_id, thread_id)

    def _agent_titles(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for manifest in self.registry.get_delegatable_agents(exclude=""):
            title = getattr(manifest, "title", None)
            if isinstance(title, str) and title.strip():
                out[manifest.id] = title.strip()
        return out

    def _agent_timeouts(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for manifest in self.registry.get_delegatable_agents(exclude=""):
            timeout = getattr(manifest, "timeout_s", None)
            if isinstance(timeout, (int, float)) and timeout > 0:
                out[manifest.id] = float(timeout)
        return out

    async def run(
        self,
        state: Mapping[str, Any],
        *,
        explicit_agent: Optional[str] = None,
        turn_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Optional[TurnOutcome]:
        """Routes the turn; runs the main agent when it is chosen.

        Direct routes (user-selected, fixed, default) are returned without
        running anything: the caller hands the turn to that agent.
        """
        turn_id = turn_id or uuid.uuid4().hex
        if explicit_agent and not self._is_visible(explicit_agent):
            # The pick is ignored and routing carries on; the refusal is recorded.
            reason = pick_rejection(self.registry, explicit_agent) or "hidden"
            await record_rejected_pick(self.audit_sink, explicit_agent, reason, turn_id, thread_id)
        decision = self.decide(state, explicit_agent)
        if decision is None:
            return None
        if decision.source != RouteSource.MAIN_AGENT:
            await self.audit_route(decision, turn_id, thread_id)
            outcome = TurnOutcome(decision=decision, turn_id=turn_id)
            notice = self.notice_for(decision, turn_id)
            if notice is not None:
                outcome.notices.append(notice)
            return outcome

        assert self.model is not None
        await self.audit_route(decision, turn_id, thread_id)
        records: List[AuditEvent] = []
        downstream = self.audit_sink

        async def _recording_sink(record: AuditEvent) -> None:
            await _emit(downstream, record)  # strict: a failed write stops the turn first
            records.append(record)

        titles = self._agent_titles()
        guard = TaskGuardMiddleware(
            allowed_agents=[a.id for a in self.registry.get_delegatable_agents(exclude="")],
            limits=self.limits,
            agent_timeouts=self._agent_timeouts(),
            agent_titles=titles,
            audit_sink=_recording_sink,
            status_sink=self.status_sink,
            turn_id=turn_id,
            thread_id=thread_id,
        )
        try:
            agent = build_main_agent(
                self.model, self.registry, guard,
                system_prompt=self.system_prompt, tool_resolver=self.tool_resolver,
            )
            result = await agent.ainvoke({"messages": list(state.get("messages") or [])})
        except OrchestrationAuditError:
            raise
        except asyncio.CancelledError:
            # Persist hand-offs that already started, then let cancel propagate.
            await store_turn_tasks(
                self.task_sink,
                build_turn_tasks(records, guard.runs, titles, turn_id=turn_id, thread_id=thread_id),
            )
            raise
        except Exception as err:
            logger.warning("Main agent failed: %s", type(err).__name__)
            fallback = self._default_decision("main_agent_failed")
            await store_turn_tasks(
                self.task_sink,
                build_turn_tasks(records, guard.runs, titles, turn_id=turn_id, thread_id=thread_id),
            )
            if fallback is None:
                raise
            await self.audit_route(fallback, turn_id, thread_id)
            outcome = TurnOutcome(
                decision=fallback, turn_id=turn_id, tasks_started=guard.calls_made, tasks=guard.runs,
                provenance=build_provenance(guard.runs, records, titles),
            )
            notice = self.notice_for(fallback, turn_id)
            if notice is not None:
                outcome.notices.append(notice)
            return outcome

        before = len(state.get("messages") or [])
        new_messages = list(result.get("messages") or [])[before:]
        provenance = build_provenance(guard.runs, records, titles)
        await store_turn_tasks(
            self.task_sink,
            build_turn_tasks(records, guard.runs, titles, turn_id=turn_id, thread_id=thread_id),
        )
        return TurnOutcome(
            decision=decision,
            turn_id=turn_id,
            messages=state_gaps(new_messages, provenance),
            provenance=provenance,
            notices=task_notices(turn_id, guard.runs),
            tasks_started=guard.calls_made,
            tasks=guard.runs,
        )


def final_answer(messages: Sequence[BaseMessage]) -> Optional[AIMessage]:
    """Returns the last AI message without tool calls, if any."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return message
    return None


__all__ = [
    "MAIN_AGENT_ID",
    "MAIN_AGENT_PROMPT",
    "HybridRouter",
    "ToolResolver",
    "TurnOutcome",
    "build_main_agent",
    "build_provenance",
    "build_turn_tasks",
    "store_turn_tasks",
    "TurnTaskSink",
    "compose_main_prompt",
    "pick_rejection",
    "record_rejected_pick",
    "rejected_pick_event",
    "record_route",
    "route_event",
    "final_answer",
    "gap_statement",
    "state_gaps",
    "task_notices",
]
