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

"""Guard around the Deep Agents ``task`` tool.

Every subagent hand-off from the main agent is one ``task`` tool call. This
middleware wraps those calls and enforces, per turn:

- policy: only agents offered to the main agent may be called; hidden or
  unknown agents are refused;
- fan-out: at most ``OrchestrationLimits.max_agents`` hand-offs;
- time: each hand-off is bounded by ``agent_timeout_s`` and by what is left of
  ``turn_timeout_s``;
- audit: ``task.started`` then exactly one of ``task.completed``,
  ``task.failed`` or ``task.timed_out`` (strict durability, so a failed audit
  write stops the turn).

Refusals, timeouts and subagent errors come back to the main agent as error
tool messages so it can answer with what it has.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Union

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import OrchestrationLimits

TASK_TOOL_NAME = "task"

AuditSink = Callable[[AuditEvent], Union[None, Awaitable[None]]]
"""Receives every orchestration audit event; may be sync or async."""

TaskStatusSink = Callable[[Dict[str, Any]], Union[None, Awaitable[None]]]
"""Receives ``task_status`` stream events (``SSETaskStatusEvent`` payloads)."""


class OrchestrationAuditError(RuntimeError):
    """A strict orchestration audit event could not be recorded."""


def _sha256(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _result_text(result: Any) -> str:
    if isinstance(result, ToolMessage):
        return str(result.content)
    if isinstance(result, Command):
        update = result.update if isinstance(result.update, dict) else {}
        messages = update.get("messages") or []
        return "\n".join(str(getattr(m, "content", m)) for m in messages)
    return str(result)


async def _emit(sink: Optional[Callable[[Any], Any]], payload: Any) -> None:
    if sink is None:
        return
    out = sink(payload)
    if inspect.isawaitable(out):
        await out


@dataclass
class _TurnBudget:
    started_at: float = field(default_factory=time.monotonic)
    calls: int = 0


class TaskGuardMiddleware(AgentMiddleware):
    """Enforces limits, policy and audit on the main agent's ``task`` calls."""

    def __init__(
        self,
        *,
        allowed_agents: Iterable[str],
        limits: Optional[OrchestrationLimits] = None,
        agent_timeouts: Optional[Dict[str, float]] = None,
        audit_sink: Optional[AuditSink] = None,
        status_sink: Optional[TaskStatusSink] = None,
        turn_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.allowed_agents = frozenset(allowed_agents)
        self.limits = limits or OrchestrationLimits()
        self.agent_timeouts = dict(agent_timeouts or {})
        self.audit_sink = audit_sink
        self.status_sink = status_sink
        self.turn_id = turn_id or uuid.uuid4().hex
        self.parent_task_id = parent_task_id
        self.thread_id = thread_id
        self._budget = _TurnBudget()

    @property
    def name(self) -> str:
        return "yarvelle_task_guard"

    @property
    def calls_made(self) -> int:
        return self._budget.calls

    def reset_turn(self, turn_id: Optional[str] = None) -> None:
        """Starts a new turn budget (call count and turn clock)."""
        self._budget = _TurnBudget()
        if turn_id:
            self.turn_id = turn_id

    def _timeout_for(self, agent_id: str) -> float:
        per_agent = min(self.agent_timeouts.get(agent_id, self.limits.agent_timeout_s), self.limits.agent_timeout_s)
        remaining = self.limits.turn_timeout_s - (time.monotonic() - self._budget.started_at)
        return max(0.0, min(per_agent, remaining))

    async def _audit(self, event: str, agent_id: str, task_id: str, **fields: Any) -> None:
        if self.audit_sink is None:
            return
        record = AuditEvent(
            event=event,  # type: ignore[arg-type]
            agent_id=agent_id,
            turn_id=self.turn_id,
            task_id=task_id,
            parent_task_id=self.parent_task_id,
            thread_id=self.thread_id,
            tool=TASK_TOOL_NAME,
            **fields,
        )
        try:
            await _emit(self.audit_sink, record)
        except Exception as err:  # strict durability: stop the turn
            raise OrchestrationAuditError(f"could not record {event} for task {task_id}") from err

    async def _status(self, agent_id: str, task_id: str, state: str, detail: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "type": "task_status",
            "turn_id": self.turn_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "state": state,
        }
        if detail:
            payload["detail"] = detail
        try:
            await _emit(self.status_sink, payload)
        except Exception:
            pass  # stream status is best effort

    @staticmethod
    def _error(tool_call_id: str, message: str) -> ToolMessage:
        return ToolMessage(content=message, tool_call_id=tool_call_id, name=TASK_TOOL_NAME, status="error")

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        call = request.tool_call
        if call.get("name") != TASK_TOOL_NAME:
            return await handler(request)

        args = call.get("args") or {}
        agent_id = str(args.get("subagent_type") or "")
        task_id = str(call.get("id") or uuid.uuid4().hex)
        input_hash = _sha256(str(args.get("description") or ""))
        audit_agent = agent_id or "unknown"

        if agent_id not in self.allowed_agents:
            await self._audit(
                "task.failed", audit_agent, task_id, allowed=False, input_hash=input_hash,
                error_code="policy.denied", reason="agent not available to the main agent",
            )
            await self._status(audit_agent, task_id, "failed", "agent not available")
            return self._error(task_id, f"Agent '{agent_id}' is not available. Choose one of the listed agents.")

        if self._budget.calls >= self.limits.max_agents:
            await self._audit(
                "task.failed", agent_id, task_id, allowed=False, input_hash=input_hash,
                error_code="limit.max_agents", reason=f"more than {self.limits.max_agents} hand-offs in one turn",
            )
            await self._status(agent_id, task_id, "failed", "hand-off limit reached")
            return self._error(
                task_id,
                f"Hand-off limit reached ({self.limits.max_agents} per turn). Answer with the results you have.",
            )

        timeout = self._timeout_for(agent_id)
        if timeout <= 0:
            await self._audit(
                "task.timed_out", agent_id, task_id, allowed=False, input_hash=input_hash,
                error_code="limit.turn_timeout", duration_ms=0.0,
            )
            await self._status(agent_id, task_id, "timed_out", "turn time budget used up")
            return self._error(task_id, "The turn's time budget is used up. Answer with the results you have.")

        self._budget.calls += 1
        await self._audit("task.started", agent_id, task_id, allowed=True, input_hash=input_hash)
        await self._status(agent_id, task_id, "started")
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(handler(request), timeout=timeout)
        except asyncio.TimeoutError:
            await self._audit(
                "task.timed_out", agent_id, task_id, input_hash=input_hash,
                error_code="limit.agent_timeout", duration_ms=(time.monotonic() - started) * 1000,
            )
            await self._status(agent_id, task_id, "timed_out", f"no answer within {timeout:g}s")
            return self._error(task_id, f"Agent '{agent_id}' did not answer within {timeout:g}s.")
        except OrchestrationAuditError:
            raise
        except Exception as err:
            await self._audit(
                "task.failed", agent_id, task_id, input_hash=input_hash,
                error_code="task.error", reason=type(err).__name__,
                duration_ms=(time.monotonic() - started) * 1000,
            )
            await self._status(agent_id, task_id, "failed")
            return self._error(task_id, f"Agent '{agent_id}' failed to answer.")

        await self._audit(
            "task.completed", agent_id, task_id, input_hash=input_hash,
            output_hash=_sha256(_result_text(result)), duration_ms=(time.monotonic() - started) * 1000,
        )
        await self._status(agent_id, task_id, "completed")
        return result

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        call = request.tool_call
        if call.get("name") != TASK_TOOL_NAME:
            return handler(request)
        # Timeouts need the async path; refuse sync hand-offs rather than run them unbounded.
        task_id = str(call.get("id") or uuid.uuid4().hex)
        return self._error(task_id, "Agent hand-offs require the async runtime.")


__all__ = [
    "TASK_TOOL_NAME",
    "AuditSink",
    "OrchestrationAuditError",
    "TaskGuardMiddleware",
    "TaskStatusSink",
]
