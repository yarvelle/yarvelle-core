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

"""Hybrid routing runtime: fixed routes, default fallback and the guarded main agent.

All models here are in-process fakes; no network or real model is used.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

import pytest
import yaml
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.orchestration import (
    HybridRouter,
    TaskGuardMiddleware,
    attachment_media_types,
    select_fixed_route,
)
from yarvelle_core.engine.orchestration.task_guard import OrchestrationAuditError
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import (
    FixedRoute,
    GuardrailFlagTrigger,
    HasAttachmentsTrigger,
    OrchestrationLimits,
    PackOrchestrationSpec,
    RouteSource,
)


class ScriptedModel(BaseChatModel):
    """Returns scripted messages in order; tool binding is a no-op."""

    script: List[BaseMessage]
    delay_s: float = 0.0
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        return self

    def _next(self) -> BaseMessage:
        if not self.script:
            return AIMessage(content="(no more script)")
        self.calls += 1
        return self.script.pop(0)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return ChatResult(generations=[ChatGeneration(message=self._next())])


def _task_call(agent_id: str, call_id: str, description: str = "do the thing") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "task", "id": call_id, "args": {"subagent_type": agent_id, "description": description}}],
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
    _write_agent(agents, "doc-reader")
    _write_agent(agents, "secret-helper", hidden=True)
    return AgentRegistry(agents_dir=agents)


def _spec(**limits: Any) -> PackOrchestrationSpec:
    return PackOrchestrationSpec(
        default_agent="budget-planner",
        fixed_routes=[
            FixedRoute(route_id="docs", when=HasAttachmentsTrigger(mime_types=["application/pdf", "image/*"]), agent_id="doc-reader"),
            FixedRoute(route_id="crisis", when=GuardrailFlagTrigger(flag="crisis"), agent_id="trip-organizer"),
        ],
        limits=OrchestrationLimits(**limits) if limits else OrchestrationLimits(),
    )


def _turn(prompt: str = "help me", **extra: Any) -> Dict[str, Any]:
    return {"messages": [HumanMessage(content=prompt)], **extra}


class Sink:
    def __init__(self) -> None:
        self.events: List[AuditEvent] = []

    async def __call__(self, event: AuditEvent) -> None:
        self.events.append(event)

    def kinds(self) -> List[str]:
        return [e.event for e in self.events]


# ------------------------------------------------------------------ fixed routes


def test_attachment_route_matches_media_wildcards() -> None:
    state = _turn(attachments=[{"mime_type": "image/png"}])
    decision = select_fixed_route(_spec(), state)
    assert decision is not None and decision.route_id == "docs" and decision.agent_id == "doc-reader"
    assert attachment_media_types({"attachments": [{"content_type": "Application/PDF; q=1"}]}) == ["application/pdf"]


def test_attachment_route_skips_unlisted_media() -> None:
    assert select_fixed_route(_spec(), _turn(attachments=[{"mime_type": "text/csv"}])) is None


def test_guardrail_flag_route_wins_over_attachments() -> None:
    state = _turn(attachments=[{"mime_type": "image/png"}], guardrail_flags=["crisis"])
    decision = select_fixed_route(_spec(), state)
    assert decision is not None and decision.route_id == "crisis"


def test_no_fixed_route_without_spec() -> None:
    assert select_fixed_route(None, _turn(attachments=[{"mime_type": "image/png"}])) is None


# ------------------------------------------------------------------ decisions


def test_without_model_falls_back_to_default_with_notice(registry: AgentRegistry) -> None:
    router = HybridRouter(registry=registry, model=None, spec=_spec())
    outcome = asyncio.run(router.run(_turn("plan my trip to the coast")))
    assert outcome is not None
    assert outcome.decision.source == RouteSource.DEFAULT_AGENT
    assert outcome.decision.agent_id == "budget-planner"
    assert outcome.decision.fallback_reason == "model_unavailable"
    assert [n.code for n in outcome.notices] == ["model_unavailable"]


def test_without_model_or_default_nothing_routes(registry: AgentRegistry) -> None:
    router = HybridRouter(registry=registry, model=None)
    assert asyncio.run(router.run(_turn())) is None


def test_fixed_route_runs_before_any_model_call(registry: AgentRegistry) -> None:
    model = ScriptedModel(script=[AIMessage(content="should not be used")])
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn(attachments=[{"mime_type": "application/pdf"}])))
    assert outcome is not None and outcome.decision.source == RouteSource.FIXED_ROUTE
    assert model.calls == 0
    assert sink.kinds() == ["route.fixed"]
    assert sink.events[0].details == {"route": {"source": "fixed_route", "route_id": "docs", "agent_id": "doc-reader"}}


def test_user_selected_agent_must_be_visible(registry: AgentRegistry) -> None:
    router = HybridRouter(registry=registry, model=None, spec=_spec())
    assert router.decide(_turn(), explicit_agent="trip-organizer").source == RouteSource.USER_SELECTED
    hidden = router.decide(_turn(), explicit_agent="secret-helper")
    assert hidden is not None and hidden.source == RouteSource.DEFAULT_AGENT


# ------------------------------------------------------------------ main agent


def test_main_agent_delegates_through_task_tool(registry: AgentRegistry) -> None:
    model = ScriptedModel(
        script=[
            _task_call("trip-organizer", "call-1", "draft an itinerary"),
            AIMessage(content="Day 1: beach."),
            AIMessage(content="Here is your plan: Day 1: beach."),
        ]
    )
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn("plan a weekend"), turn_id="turn-1"))
    assert outcome is not None and outcome.decision.source == RouteSource.MAIN_AGENT
    assert outcome.tasks_started == 1
    assert outcome.messages[-1].content == "Here is your plan: Day 1: beach."
    tool_results = [m for m in outcome.messages if isinstance(m, ToolMessage)]
    assert tool_results and "Day 1: beach." in str(tool_results[0].content)
    assert sink.kinds() == ["route.main_agent", "task.started", "task.completed"]
    done = sink.events[2]
    assert (done.turn_id, done.task_id, done.agent_id) == ("turn-1", "call-1", "trip-organizer")
    assert done.input_hash and done.output_hash and done.duration_ms is not None


def test_main_agent_is_offered_only_visible_registry_agents(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.orchestration.runtime import _subagent_specs

    names = {s["name"] for s in _subagent_specs(registry, ScriptedModel(script=[]), None)}
    assert names == {"budget-planner", "trip-organizer", "doc-reader"}
    assert "general-purpose" not in names


def test_main_agent_has_only_the_task_tool(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.orchestration.runtime import build_main_agent

    guard = TaskGuardMiddleware(allowed_agents=["budget-planner"])
    agent = build_main_agent(ScriptedModel(script=[]), registry, guard)
    tools_node = agent.get_graph().nodes.get("tools")
    assert tools_node is not None
    assert set(tools_node.data.tools_by_name) == {"task"}


def test_hidden_or_unknown_agent_is_refused(registry: AgentRegistry) -> None:
    model = ScriptedModel(script=[_task_call("secret-helper", "call-h"), AIMessage(content="I could not reach that agent.")])
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn()))
    assert outcome is not None and outcome.tasks_started == 0
    assert sink.kinds() == ["route.main_agent", "task.failed"]
    assert sink.events[1].error_code == "policy.denied" and sink.events[1].allowed is False


def test_fan_out_is_capped_at_max_agents(registry: AgentRegistry) -> None:
    model = ScriptedModel(
        script=[
            _task_call("budget-planner", "c1"),
            AIMessage(content="budget ok"),
            _task_call("trip-organizer", "c2"),
            AIMessage(content="trip ok"),
            _task_call("doc-reader", "c3"),
            AIMessage(content="combined answer"),
        ]
    )
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(max_agents=2), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn()))
    assert outcome is not None and outcome.tasks_started == 2
    assert sink.kinds().count("task.started") == 2
    assert all(e.event != "task.started" or e.task_id != "c3" for e in sink.events)


def test_subagent_timeout_is_reported_to_main_agent(registry: AgentRegistry) -> None:
    guard = TaskGuardMiddleware(
        allowed_agents=["budget-planner"],
        limits=OrchestrationLimits(agent_timeout_s=0.05, turn_timeout_s=1.0),
    )

    class _Req:
        tool_call = {"name": "task", "id": "slow-1", "args": {"subagent_type": "budget-planner", "description": "x"}}

    async def slow_handler(_req: Any) -> Any:
        await asyncio.sleep(1)

    sink = Sink()
    guard.audit_sink = sink
    result = asyncio.run(guard.awrap_tool_call(_Req(), slow_handler))
    assert isinstance(result, ToolMessage) and result.status == "error"
    assert sink.kinds() == ["task.started", "task.timed_out"]
    assert sink.events[1].error_code == "limit.agent_timeout"


def test_failed_strict_audit_write_stops_the_turn(registry: AgentRegistry) -> None:
    async def broken_sink(_event: AuditEvent) -> None:
        raise OSError("disk full")

    guard = TaskGuardMiddleware(allowed_agents=["budget-planner"], audit_sink=broken_sink)

    class _Req:
        tool_call = {"name": "task", "id": "a-1", "args": {"subagent_type": "budget-planner", "description": "x"}}

    async def handler(_req: Any) -> Any:
        return ToolMessage(content="ok", tool_call_id="a-1")

    with pytest.raises(OrchestrationAuditError):
        asyncio.run(guard.awrap_tool_call(_Req(), handler))


def test_main_agent_failure_falls_back_to_default(registry: AgentRegistry) -> None:
    class Exploding(ScriptedModel):
        async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
            raise RuntimeError("provider down")

    sink = Sink()
    router = HybridRouter(registry=registry, model=Exploding(script=[]), spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn()))
    assert outcome is not None
    assert outcome.decision.source == RouteSource.DEFAULT_AGENT
    assert outcome.decision.fallback_reason == "main_agent_failed"
    assert [n.code for n in outcome.notices] == ["main_agent_failed"]
    # The main agent was chosen first, then the turn fell back to the default.
    assert sink.kinds() == ["route.main_agent", "route.default"]


# ------------------------------------------------------------------ graph wiring


def test_orchestrator_node_takes_fixed_route_without_model(registry: AgentRegistry) -> None:
    from yarvelle_core.workflows.nodes import OrchestratorNode

    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec())
    result = asyncio.run(node.execute(_turn(guardrail_flags=["crisis"])))
    assert result["next_step"] == "trip-organizer"
    assert result["route_decision"]["route_id"] == "crisis"
    assert "orchestration_notices" not in result


def test_orchestrator_node_never_guesses_from_keywords(registry: AgentRegistry) -> None:
    from yarvelle_core.workflows.nodes import OrchestratorNode

    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec())
    result = asyncio.run(node.execute(_turn("please coordinate a trip and deliberate on the budget")))
    assert result["next_step"] == "budget-planner"
    assert result["execution_plan"]["mode"] == "single"
    assert [n["code"] for n in result["orchestration_notices"]] == ["model_unavailable"]


def test_orchestrator_node_hands_model_turns_to_main_agent(registry: AgentRegistry) -> None:
    from yarvelle_core.workflows.nodes import OrchestratorNode

    model = ScriptedModel(script=[])
    node = OrchestratorNode(model=model, registry=registry, orchestration=_spec(), main_agent_enabled=True)
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert result["next_step"] == "main-agent"
    assert result["route_decision"] == {"source": "main_agent"}
    assert result["current_agent"] == "main-agent"
    assert model.calls == 0


def test_main_agent_node_returns_answer_messages(registry: AgentRegistry) -> None:
    from yarvelle_core.workflows.nodes import MainAgentNode

    model = ScriptedModel(
        script=[_task_call("budget-planner", "b-1"), AIMessage(content="Save 10%."), AIMessage(content="Plan: save 10%.")]
    )
    sink = Sink()
    node = MainAgentNode(model=model, registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn("budget help")))
    assert result["next_step"] == "output_guardrail"
    assert result["messages"][-1].content == "Plan: save 10%."
    assert result["route_decision"] == {"source": "main_agent"}
    assert sink.kinds() == ["route.main_agent", "task.started", "task.completed"]


def test_builder_wires_main_agent_node(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.builder import GraphBuilder

    builder = GraphBuilder(
        model=ScriptedModel(script=[]),
        registry=registry,
        orchestration=_spec(),
        orchestration_audit_sink=Sink(),
    )
    graph = builder.build()
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "main_agent"} <= nodes
