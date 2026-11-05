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

"""Scripted fake chat model and the fake eval backend.

The fake answers from a per-turn script and never touches the network, so a
scenario run on it is free and fully repeatable. One model instance plays
every role, the same way the runtime hands one model to the main agent and
each subagent. It tells the roles apart by the agent name the runtime puts in
the run metadata, then by the persona marker ``You are the <id> agent.``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Sequence, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr

from yarvelle_core.testing.orch_eval.backends import FREE, CostTable, Role
from yarvelle_core.testing.orch_eval.schema import FakeAgentStep, FakeScript

MAIN_ROLE = "__main__"
"""Script key for the main agent (and any call that names no agent)."""

SUGGESTION_ROLE = "__suggestion__"
"""Role for follow-up suggestion calls, which never consume the script."""

MAIN_AGENT_NAME = "main-agent"
PERSONA_MARKER = "You are the "
TASK_TOOL = "task"
ROUTE_DECISION_TOOL = "OrchestratorDecision"
"""Tool name of the routing model's structured output (its schema's name)."""

Step = Tuple[str, Any]


class FakeScriptError(RuntimeError):
    """Raised by the fake model for a scripted ``error`` step."""


@dataclass(frozen=True)
class FakeCall:
    """One model call the fake answered."""

    turn: int
    role: str
    node: Optional[str]
    outcome: str  # "scripted", "error", "exhausted" or "auxiliary"


class ScriptedFakeChatModel(BaseChatModel):
    """Chat model that replays a per-turn script for the main agent and each agent.

    Load a turn with :meth:`load_turn` before running it. Scripted steps are
    consumed in order per role. A call with nothing left to play returns a
    marker reply and is recorded as ``exhausted``; :meth:`problems` reports it,
    together with steps left unused at the end of the turn.
    """

    _queues: Dict[str, List[Step]] = PrivateAttr(default_factory=dict)
    _calls: List[FakeCall] = PrivateAttr(default_factory=list)
    _agent_ids: frozenset = PrivateAttr(default_factory=frozenset)
    _turn: int = PrivateAttr(default=0)
    _ids: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "orch-eval-scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedFakeChatModel":
        return self

    # ------------------------------------------------------------ scripting

    def set_agents(self, agent_ids: Iterable[str]) -> None:
        """Declares the pack's agent ids, used to recognise who is calling."""
        self._agent_ids = frozenset(agent_ids)

    def load_turn(self, turn: int, script: Optional[FakeScript]) -> None:
        """Replaces the queues with ``script`` for turn number ``turn``."""
        self._turn = turn
        queues: Dict[str, List[Step]] = {}
        if script is not None:
            main: List[Step] = []
            for step in script.main:
                if step.task is not None:
                    main.append(("task", list(step.task)))
                elif step.route is not None:
                    main.append(("route", step.route))
                elif step.error is not None:
                    main.append(("error", step.error))
                else:
                    main.append(("answer", step.answer))
            if main:
                queues[MAIN_ROLE] = main
            for agent_id, steps in script.agents.items():
                queues[agent_id] = [_agent_step(s) for s in steps]
        self._queues = queues

    @property
    def calls(self) -> List[FakeCall]:
        return list(self._calls)

    def calls_for_turn(self, turn: int) -> List[FakeCall]:
        return [c for c in self._calls if c.turn == turn]

    def unused_steps(self) -> Dict[str, int]:
        """Steps still queued, per role."""
        return {role: len(q) for role, q in self._queues.items() if q}

    def problems(self, turn: int) -> List[str]:
        """Script mismatches for ``turn``: exhausted calls and unused steps."""
        out = [
            f"{c.role} was called with no scripted reply left"
            for c in self.calls_for_turn(turn)
            if c.outcome == "exhausted"
        ]
        out.extend(f"{role} has {n} unused scripted step(s)" for role, n in sorted(self.unused_steps().items()))
        return out

    # -------------------------------------------------------------- replies

    def _role(self, messages: List[BaseMessage], run_manager: Any) -> str:
        tags = list(getattr(run_manager, "tags", None) or [])
        if "suggestion" in tags:
            return SUGGESTION_ROLE
        meta = getattr(run_manager, "metadata", None) or {}
        name = meta.get("lc_agent_name")
        if name == MAIN_AGENT_NAME:
            return MAIN_ROLE
        if isinstance(name, str) and name in self._agent_ids:
            return name
        system = next((m for m in messages if isinstance(m, SystemMessage)), None)
        text = str(system.content) if system is not None else ""
        if PERSONA_MARKER in text:
            candidate = text.split(PERSONA_MARKER, 1)[1].split(" agent", 1)[0].strip()
            if candidate in self._agent_ids:
                return candidate
        return MAIN_ROLE

    def _next_id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}-t{self._turn}-{self._ids}"

    def _reply(self, messages: List[BaseMessage], run_manager: Any) -> BaseMessage:
        role = self._role(messages, run_manager)
        meta = getattr(run_manager, "metadata", None) or {}
        node = meta.get("langgraph_node")
        if role == SUGGESTION_ROLE:
            self._calls.append(FakeCall(self._turn, role, node, "auxiliary"))
            return AIMessage(content="[]")
        queue = self._queues.get(role) or []
        if not queue:
            self._calls.append(FakeCall(self._turn, role, node, "exhausted"))
            return AIMessage(content=f"[no scripted reply left for {role}]")
        kind, value = queue.pop(0)
        if kind == "error":
            self._calls.append(FakeCall(self._turn, role, node, "error"))
            raise FakeScriptError(f"scripted failure: {value}")
        self._calls.append(FakeCall(self._turn, role, node, "scripted"))
        if kind == "task":
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": TASK_TOOL,
                        "id": self._next_id("call"),
                        "args": {"subagent_type": agent_id, "description": f"Handle your part of: {_last_user(messages)}"},
                    }
                    for agent_id in value
                ],
            )
        if kind == "route":
            # The routing model's structured pick (read through the tool call).
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": ROUTE_DECISION_TOOL,
                        "id": self._next_id("route"),
                        "args": {"agent_id": value, "reasoning": "Scripted routing pick.", "instructions": ""},
                    }
                ],
            )
        if kind == "tool":
            return AIMessage(
                content="",
                tool_calls=[{"name": value, "id": self._next_id("tool"), "args": {"query": _last_user(messages)}}],
            )
        return AIMessage(content=str(value))

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages, run_manager))])

    async def _agenerate(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages, run_manager))])

    async def _astream(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        msg = self._reply(messages, run_manager)
        calls = getattr(msg, "tool_calls", None) or []
        chunk = AIMessageChunk(
            content=msg.content,
            tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i, "type": "tool_call_chunk"}
                for i, c in enumerate(calls)
            ],
        )
        if run_manager is not None and msg.content:
            await run_manager.on_llm_new_token(str(msg.content), chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


def _agent_step(step: Any) -> Step:
    if isinstance(step, str):
        return ("answer", step)
    assert isinstance(step, FakeAgentStep)
    if step.error is not None:
        return ("error", step.error)
    return ("tool", step.tool)


def _last_user(messages: List[BaseMessage]) -> str:
    for m in reversed(messages):
        if getattr(m, "type", "") == "human":
            return str(m.content)[:200]
    return ""


class FakeBackend:
    """The scripted fake behind :class:`EvalBackend`. Free and offline."""

    name = "fake"
    cost_per_mtok: CostTable = FREE

    def __init__(self) -> None:
        self.model = ScriptedFakeChatModel()

    def model_for(self, role: Role) -> ScriptedFakeChatModel:
        return self.model

    def describe(self) -> dict[str, Any]:
        return {"backend": "fake", "model": "scripted", "temperature": 0, "seed": None}

    def set_agents(self, agent_ids: Iterable[str]) -> None:
        self.model.set_agents(agent_ids)

    def load_turn(self, turn: int, script: Optional[FakeScript]) -> None:
        self.model.load_turn(turn, script)

    def problems(self, turn: int) -> List[str]:
        return self.model.problems(turn)


__all__ = [
    "FakeBackend",
    "FakeCall",
    "FakeScriptError",
    "MAIN_ROLE",
    "ScriptedFakeChatModel",
]
