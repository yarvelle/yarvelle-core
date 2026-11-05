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

"""Hand-off hardening: timeouts, failures, cancel, call caps and the stream.

Every model here is a scripted in-process fake; nothing calls a real model.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import pytest
import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool

from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.orchestration import HybridRouter, SubagentCallCapMiddleware, TaskGuardMiddleware, TaskRun
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID, task_notices
from yarvelle_core.engine.orchestration.task_guard import _ACTIVE_TASK
from yarvelle_core.engine.service import is_subagent_token
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import OrchestrationLimits, PackOrchestrationSpec, SSETaskStatusEvent

MAIN = "__main__"


class AgentScriptedModel(BaseChatModel):
    """Scripted fake that answers per agent, keyed by its system prompt.

    ``scripts`` maps an agent id (or ``__main__``) to the messages it returns
    in order. ``delays`` and ``failures`` make one agent slow or broken.
    """

    scripts: Dict[str, List[BaseMessage]]
    delays: Dict[str, float] = {}
    failures: List[str] = []
    cancelled: List[str] = []
    calls: Dict[str, int] = {}

    @property
    def _llm_type(self) -> str:
        return "agent-scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "AgentScriptedModel":
        return self

    @staticmethod
    def _who(messages: List[BaseMessage]) -> str:
        system = next((m for m in messages if isinstance(m, SystemMessage)), None)
        text = str(system.content) if system is not None else ""
        marker = "You are the "
        if marker in text:
            return text.split(marker, 1)[1].split(" agent", 1)[0]
        return MAIN

    async def _reply(self, messages: List[BaseMessage]) -> BaseMessage:
        who = self._who(messages)
        self.calls[who] = self.calls.get(who, 0) + 1
        if who in self.failures:
            raise RuntimeError(f"{who} provider error")
        delay = self.delays.get(who, 0.0)
        if delay:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self.cancelled.append(who)
                raise
        script = self.scripts.get(who) or []
        return script.pop(0) if script else AIMessage(content=f"{who} has nothing more to say")

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("async only")

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=await self._reply(messages))])

    async def _astream(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        msg = await self._reply(messages)
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


def _tasks(*pairs: tuple[str, str]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "task", "id": call_id, "args": {"subagent_type": agent, "description": f"work for {agent}"}}
            for agent, call_id in pairs
        ],
    )


def _write_agent(root: Path, agent_id: str, **fields: Any) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    data: Dict[str, Any] = {
        "id": agent_id,
        "title": agent_id.replace("-", " ").title(),
        "description": f"{agent_id} helper",
        "persona": "persona.md",
        "tools": [],
        "skills": [],
    }
    data.update(fields)
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (agent_dir / "persona.md").write_text(f"You are the {agent_id} agent.\n", encoding="utf-8")


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    _write_agent(agents, "budget-planner")
    _write_agent(agents, "trip-organizer")
    _write_agent(agents, "doc-reader", max_iterations=1)
    return AgentRegistry(agents_dir=agents)


def _spec(**limits: Any) -> PackOrchestrationSpec:
    return PackOrchestrationSpec(default_agent="budget-planner", limits=OrchestrationLimits(**limits))


def _turn(prompt: str = "help me") -> Dict[str, Any]:
    return {"messages": [HumanMessage(content=prompt)]}


class Sink:
    def __init__(self) -> None:
        self.events: List[AuditEvent] = []

    async def __call__(self, event: AuditEvent) -> None:
        self.events.append(event)

    def by_task(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for e in self.events:
            if e.event.startswith("task."):
                out.setdefault(str(e.task_id), []).append(e.event)
        return out


class StatusSink:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    async def __call__(self, payload: Dict[str, Any]) -> None:
        SSETaskStatusEvent.model_validate(payload)
        self.events.append(payload)

    def states(self, task_id: str) -> List[str]:
        return [e["state"] for e in self.events if e["task_id"] == task_id]


def _tool_texts(messages: Sequence[BaseMessage]) -> Dict[str, ToolMessage]:
    return {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}


# ------------------------------------------------------------------ timeouts and failures


def test_slow_subagent_times_out_while_others_complete(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "slow"), ("trip-organizer", "fast")), AIMessage(content="Here is the trip.")],
            "trip-organizer": [AIMessage(content="Day 1: beach.")],
            "budget-planner": [AIMessage(content="late budget")],
        },
        delays={"budget-planner": 5.0},
    )
    sink, status = Sink(), StatusSink()
    router = HybridRouter(
        registry=registry, model=model, spec=_spec(agent_timeout_s=0.3, turn_timeout_s=10), audit_sink=sink, status_sink=status
    )
    started = time.monotonic()
    outcome = asyncio.run(router.run(_turn(), turn_id="t-1"))
    assert time.monotonic() - started < 4.0
    assert outcome is not None and outcome.messages[-1].content.startswith("Here is the trip.")
    assert "Budget Planner did not answer" in outcome.messages[-1].content
    assert sink.by_task() == {"slow": ["task.started", "task.timed_out"], "fast": ["task.started", "task.completed"]}
    tools = _tool_texts(outcome.messages)
    assert tools["slow"].status == "error" and "did not answer" in str(tools["slow"].content)
    assert "Day 1: beach." in str(tools["fast"].content)
    assert status.states("slow") == ["started", "timed_out"] and status.states("fast") == ["started", "completed"]
    assert [(n.code, n.agent_ids) for n in outcome.notices] == [("partial_failure", ["budget-planner"])]
    assert {(r.task_id, r.state) for r in outcome.tasks} == {("slow", "timed_out"), ("fast", "completed")}


def test_one_failure_is_surfaced_and_the_turn_still_answers(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content="Partial plan.")],
            "trip-organizer": [AIMessage(content="Day 1: beach.")],
        },
        failures=["budget-planner"],
    )
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn()))
    assert outcome is not None and outcome.decision.source.value == "main_agent"
    assert outcome.messages[-1].content.startswith("Partial plan.")
    assert "did not answer" in outcome.messages[-1].content
    assert sink.by_task()["b"] == ["task.started", "task.failed"]
    failed = next(e for e in sink.events if e.event == "task.failed")
    assert failed.error_code == "task.error" and failed.reason == "RuntimeError"
    assert _tool_texts(outcome.messages)["b"].status == "error"
    notices = [n for n in outcome.notices if n.code == "partial_failure"]
    assert len(notices) == 1 and notices[0].agent_ids == ["budget-planner"]
    assert "budget-planner" not in notices[0].message


# ------------------------------------------------------------------ cancel


def test_user_cancel_cancels_in_flight_tasks(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content="never")]},
        delays={"budget-planner": 30.0, "trip-organizer": 30.0},
    )
    sink, status = Sink(), StatusSink()
    router = HybridRouter(
        registry=registry, model=model, spec=_spec(agent_timeout_s=60, turn_timeout_s=60), audit_sink=sink, status_sink=status
    )

    async def scenario() -> None:
        turn = asyncio.create_task(router.run(_turn()))
        for _ in range(200):
            if sum(1 for e in status.events if e["state"] == "started") == 2:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 5.0
    assert sorted(model.cancelled) == ["budget-planner", "trip-organizer"]
    assert sink.by_task() == {"b": ["task.started", "task.cancelled"], "t": ["task.started", "task.cancelled"]}
    assert status.states("b")[-1] == "cancelled" and status.states("t")[-1] == "cancelled"


# ------------------------------------------------------------------ call cap


def test_subagent_call_cap_flags_truncation(tmp_path: Path) -> None:
    @tool
    def lookup(query: str) -> str:
        """Looks something up."""
        return "found it"

    agents = tmp_path / "agents"
    _write_agent(agents, "doc-reader", max_iterations=1)
    _write_agent(agents, "budget-planner")
    registry = AgentRegistry(agents_dir=agents, tool_resolver=lambda manifest, names: [lookup] if manifest.id == "doc-reader" else [])

    loop_call = AIMessage(content="", tool_calls=[{"name": "lookup", "id": "l", "args": {"query": "x"}}])
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("doc-reader", "d")), AIMessage(content="Here is what I found so far.")],
            "doc-reader": [loop_call.model_copy(update={"tool_calls": [{**loop_call.tool_calls[0], "id": f"l{i}"}]}) for i in range(5)],
        },
    )
    sink, status = Sink(), StatusSink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink, status_sink=status)
    outcome = asyncio.run(router.run(_turn()))
    assert outcome is not None
    # max_iterations 1 -> two model calls, then the cap ends the run.
    assert model.calls["doc-reader"] == 2
    assert [r.truncated for r in outcome.tasks] == [True]
    done = next(e for e in sink.events if e.event == "task.completed")
    assert done.details == {"truncated": True}
    assert status.events[-1]["detail"] == "truncated"
    assert [(n.code, n.agent_ids) for n in outcome.notices] == [("truncated", ["doc-reader"])]
    assert "call limit" in str(_tool_texts(outcome.messages)["d"].content)


def test_call_cap_counts_only_the_subagents_own_calls() -> None:
    cap = SubagentCallCapMiddleware("doc-reader", max_iterations=2)
    assert cap.max_model_calls == 3
    run = TaskRun(agent_id="doc-reader", task_id="x")
    token = _ACTIVE_TASK.set(run)
    try:
        assert cap.before_model({"messages": [HumanMessage("q"), AIMessage("a"), AIMessage("b")]}, None) is None
        assert run.truncated is False
        out = cap.before_model({"messages": [HumanMessage("q"), *[AIMessage(str(i)) for i in range(3)]]}, None)
    finally:
        _ACTIVE_TASK.reset(token)
    assert out is not None and out["jump_to"] == "end" and run.truncated is True
    assert task_notices("t", [run])[0].code == "truncated"


# ------------------------------------------------------------------ stream


def test_stream_carries_task_status_and_hides_subagent_tokens(registry: AgentRegistry) -> None:
    from langgraph.graph import END, START, StateGraph

    from yarvelle_core.workflows.nodes import MainAgentNode
    from yarvelle_core.workflows.state import AgentState

    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("trip-organizer", "t"), ("budget-planner", "b")), AIMessage(content="FINAL ANSWER")],
            "trip-organizer": [AIMessage(content="SUBAGENT TRIP TOKENS")],
        },
        failures=["budget-planner"],
    )
    node = MainAgentNode(model=model, registry=registry, orchestration=_spec(), audit_sink=Sink())
    graph = StateGraph(AgentState)
    graph.add_node("main_agent", node.execute)
    graph.add_edge(START, "main_agent")
    graph.add_edge("main_agent", END)
    compiled = graph.compile()

    async def collect() -> List[Dict[str, Any]]:
        return [ev async for ev in compiled.astream_events(_turn(), version="v2")]

    events = asyncio.run(collect())
    tokens = [ev for ev in events if ev["event"] == "on_chat_model_stream"]
    shown = "".join(str(ev["data"]["chunk"].content) for ev in tokens if not is_subagent_token(ev.get("metadata")))
    hidden = "".join(str(ev["data"]["chunk"].content) for ev in tokens if is_subagent_token(ev.get("metadata")))
    assert "SUBAGENT TRIP TOKENS" in hidden and "SUBAGENT TRIP TOKENS" not in shown
    assert "FINAL ANSWER" in shown
    custom = [(ev["name"], ev["data"]) for ev in events if ev["event"] == "on_custom_event"]
    statuses = [(d["task_id"], d["state"]) for n, d in custom if n == "task_status"]
    assert ("t", "started") in statuses and ("t", "completed") in statuses and ("b", "failed") in statuses
    notices = [d for n, d in custom if n == "orchestration_notice"]
    assert [n["code"] for n in notices] == ["partial_failure"]


def test_main_agent_tokens_are_never_flagged_as_subagent() -> None:
    assert not is_subagent_token({"lc_agent_name": MAIN_AGENT_ID, "langgraph_checkpoint_ns": "main_agent:1|model:2"})
    assert not is_subagent_token({"lc_agent_name": "some-agent", "langgraph_checkpoint_ns": "agent:1"})
    assert is_subagent_token({"ls_agent_type": "subagent"})
    assert is_subagent_token({"lc_agent_name": "trip-organizer", "langgraph_checkpoint_ns": "main_agent:1|tools:2|model:3"})
    assert not is_subagent_token(None)


# ------------------------------------------------------------------ no legacy path


def test_legacy_dispatcher_is_gone_and_no_mock_reply_exists() -> None:
    assert importlib.util.find_spec("yarvelle_core.workflows.dispatcher") is None
    import yarvelle_core
    import yarvelle_core.workflows as workflows

    assert not hasattr(workflows, "ExecutionDispatcher")
    root = Path(yarvelle_core.__file__).parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Response from {agent_id}" not in text, path
        assert "ExecutionDispatcher" not in text, path


def test_failed_and_timed_out_hand_offs_never_return_a_mock_string(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content="ok")]},
        delays={"trip-organizer": 5.0},
        failures=["budget-planner"],
    )
    router = HybridRouter(registry=registry, model=model, spec=_spec(agent_timeout_s=0.2, turn_timeout_s=5))
    outcome = asyncio.run(router.run(_turn("plan a weekend")))
    assert outcome is not None
    for message in outcome.messages:
        assert "Response from" not in str(message.content)
        assert "plan a weekend" not in str(message.content) or isinstance(message, HumanMessage)


def test_builder_has_no_dispatcher_node(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.builder import GraphBuilder

    graph = GraphBuilder(model=AgentScriptedModel(scripts={}), registry=registry, orchestration=_spec(), orchestration_audit_sink=Sink()).build()
    nodes = set(graph.get_graph().nodes)
    assert "dispatcher" not in nodes and {"main_agent", "deliberation"} <= nodes
