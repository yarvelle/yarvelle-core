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

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

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
    TaskGuardMiddleware,
    TaskStatusSink,
    _emit,
)
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import (
    OrchestrationLimits,
    PackOrchestrationSpec,
    RouteDecision,
    RouteSource,
    SSEOrchestrationNoticeEvent,
)

logger = logging.getLogger(__name__)

MAIN_AGENT_ID = "main-agent"

MAIN_AGENT_PROMPT = (
    "You coordinate a team of specialist agents. Answer directly when no "
    "specialist is needed. Otherwise hand each part of the request to the best "
    "matching agent with the task tool, then combine their answers into one "
    "reply. Use only the listed agents."
)

ToolResolver = Callable[[str, List[str]], List[Any]]
"""Maps (agent_id, declared tool names) to runnable tools for that subagent."""

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
        system_prompt=system_prompt or MAIN_AGENT_PROMPT,
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
    ) -> None:
        self.registry = registry
        self.model = model
        self.spec = spec
        self.default_agent = (spec.default_agent if spec is not None else None) or default_agent
        self.audit_sink = audit_sink
        self.status_sink = status_sink
        self.system_prompt = system_prompt
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
        """Records ``route.fixed`` / ``route.default`` (strict durability)."""
        if self.audit_sink is None:
            return
        if decision.source == RouteSource.FIXED_ROUTE:
            event = "route.fixed"
        elif decision.source == RouteSource.DEFAULT_AGENT:
            event = "route.default"
        else:
            return
        record = AuditEvent(
            event=event,  # type: ignore[arg-type]
            agent_id=decision.agent_id or MAIN_AGENT_ID,
            turn_id=turn_id,
            thread_id=thread_id,
            details=decision.to_audit_payload(),
        )
        try:
            await _emit(self.audit_sink, record)
        except Exception as err:
            raise OrchestrationAuditError(f"could not record {event}") from err

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
        guard = TaskGuardMiddleware(
            allowed_agents=[a.id for a in self.registry.get_delegatable_agents(exclude="")],
            limits=self.limits,
            agent_timeouts=self._agent_timeouts(),
            audit_sink=self.audit_sink,
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
        except Exception as err:
            logger.warning("Main agent failed: %s", type(err).__name__)
            fallback = self._default_decision("main_agent_failed")
            if fallback is None:
                raise
            await self.audit_route(fallback, turn_id, thread_id)
            outcome = TurnOutcome(decision=fallback, turn_id=turn_id, tasks_started=guard.calls_made)
            notice = self.notice_for(fallback, turn_id)
            if notice is not None:
                outcome.notices.append(notice)
            return outcome

        before = len(state.get("messages") or [])
        new_messages = list(result.get("messages") or [])[before:]
        return TurnOutcome(
            decision=decision,
            turn_id=turn_id,
            messages=new_messages,
            tasks_started=guard.calls_made,
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
    "final_answer",
]
