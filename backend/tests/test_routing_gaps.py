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

"""Routing gaps: refused hidden picks, audited model routes and the built-in graph.

Covers three gaps: a caller could pick a hidden agent directly, model-picked
and built-in document routes left no route record, and the service's
built-in graph never routed. All models are in-process fakes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest
from langchain_core.messages import AIMessage

from tests.test_hybrid_routing import ScriptedModel, Sink, _spec, _task_call, _turn, _write_agent
from yarvelle_core.agents import AgentRegistry
from yarvelle_core.schemas.manifest import AgentManifest
from yarvelle_core.engine.orchestration import HybridRouter
from yarvelle_core.engine.orchestration.routing import BUILTIN_DOCUMENT_ROUTE_ID
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID, pick_rejection, rejected_pick_event
from yarvelle_core.engine.orchestration.task_guard import OrchestrationAuditError
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteSource
from yarvelle_core.workflows.nodes import OrchestratorNode


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    for agent_id in ("budget-planner", "trip-organizer", "doc-reader"):
        _write_agent(agents, agent_id)
    _write_agent(agents, "secret-helper", hidden=True)
    return AgentRegistry(agents_dir=agents)


def _pick(agent_id: str, call_id: str = "pick-1") -> AIMessage:
    """A routing model's structured pick, as a tool call."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "OrchestratorDecision",
                "id": call_id,
                "args": {"agent_id": agent_id, "reasoning": "fits", "instructions": ""},
            }
        ],
    )


def _domain(domain: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "DomainClassification", "id": "dom-1", "args": {"domain": domain, "category": ""}}],
    )


class _Catalog:
    """Returns the given agents for any search."""

    def __init__(self, agents: List[AgentManifest]) -> None:
        self.agents = agents
        self.searches = 0

    async def search_agents(self, **kwargs: Any) -> List[AgentManifest]:
        self.searches += 1
        return list(self.agents)


# ------------------------------------------------------------------ hidden picks


def test_pick_rejection_reasons(registry: AgentRegistry) -> None:
    assert pick_rejection(registry, "budget-planner") is None
    assert pick_rejection(registry, "secret-helper") == "hidden"
    assert pick_rejection(registry, "nobody") == "unknown"
    assert pick_rejection(None, "secret-helper") is None


def test_rejected_pick_event_shape() -> None:
    event = rejected_pick_event("secret-helper", "hidden", turn_id="t-1", thread_id="th-1")
    assert event.event == "route.rejected" and event.allowed is False
    assert event.reason == "agent_pick_hidden"
    assert event.details == {"rejected_pick": {"agent_id": "secret-helper", "reason": "hidden"}}


def test_router_records_a_refused_hidden_pick(registry: AgentRegistry) -> None:
    model = ScriptedModel(script=[_task_call("budget-planner", "c1"), AIMessage(content="ok"), AIMessage(content="done")])
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = asyncio.run(router.run(_turn(), explicit_agent="secret-helper", turn_id="turn-h"))
    assert outcome is not None
    assert sink.kinds()[:2] == ["route.rejected", "route.main_agent"]
    assert sink.events[0].agent_id == "secret-helper" and sink.events[0].turn_id == "turn-h"


def test_router_refusal_audit_failure_stops_the_turn(registry: AgentRegistry) -> None:
    async def broken(event: Any) -> None:
        raise OSError("disk full")

    router = HybridRouter(registry=registry, model=None, spec=_spec(), audit_sink=broken)
    with pytest.raises(OrchestrationAuditError):
        asyncio.run(router.run(_turn(), explicit_agent="secret-helper"))


def test_node_refuses_a_hidden_pick_and_routes_the_turn(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=sink)
    state = _turn("plan a weekend", explicit_agent="secret-helper", current_agent="secret-helper", turn_id="turn-r")
    result = asyncio.run(node.execute(state))
    assert sink.kinds() == ["route.rejected", "route.default"]
    assert sink.events[0].details["rejected_pick"] == {"agent_id": "secret-helper", "reason": "hidden"}
    assert result["current_agent"] == "budget-planner"
    assert result["explicit_agent"] is None
    assert result["route_decision"]["source"] == "default_agent"


def test_node_refused_pick_goes_to_the_main_agent(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(
        model=ScriptedModel(script=[]), registry=registry, orchestration=_spec(), main_agent_enabled=True, audit_sink=sink
    )
    result = asyncio.run(node.execute(_turn(explicit_agent="secret-helper")))
    assert sink.kinds() == ["route.rejected"]
    assert result["next_step"] == MAIN_AGENT_ID and result["explicit_agent"] is None


def test_node_keeps_visible_picks_and_the_orchestrator(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn(explicit_agent="trip-organizer")))
    assert result["current_agent"] == "trip-organizer"
    assert sink.kinds() == ["route.user_selected"]
    sink.events.clear()
    result = asyncio.run(node.execute(_turn("plan", explicit_agent="orchestrator")))
    assert "route.rejected" not in sink.kinds()


# ------------------------------------------------------------------ model-picked and built-in routes


def test_single_hop_pick_is_recorded(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(
        model=ScriptedModel(script=[_pick("trip-organizer")]), registry=registry, orchestration=_spec(), audit_sink=sink
    )
    result = asyncio.run(node.execute(_turn("plan a weekend", turn_id="turn-c")))
    assert result["current_agent"] == "trip-organizer"
    assert result["route_decision"] == {"source": "model_classified", "agent_id": "trip-organizer"}
    assert sink.kinds() == ["route.classified"]
    assert sink.events[0].turn_id == "turn-c" and sink.events[0].agent_id == "trip-organizer"


def test_single_hop_failure_falls_back_with_a_notice(registry: AgentRegistry) -> None:
    sink = Sink()
    unusable = [AIMessage(content="not json"), AIMessage(content="still not json")]
    node = OrchestratorNode(model=ScriptedModel(script=unusable), registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert result["current_agent"] == "budget-planner"
    assert result["route_decision"] == {
        "source": "default_agent",
        "agent_id": "budget-planner",
        "fallback_reason": "main_agent_failed",
    }
    assert [n["code"] for n in result["orchestration_notices"]] == ["main_agent_failed"]
    assert sink.kinds() == ["route.default"]


def test_single_hop_unknown_pick_falls_back(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=ScriptedModel(script=[_pick("nobody")]), registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert result["route_decision"]["source"] == "default_agent"
    assert sink.kinds() == ["route.default"]


def test_two_hop_pick_is_recorded(registry: AgentRegistry) -> None:
    sink = Sink()
    catalog = _Catalog([registry.get("trip-organizer")])
    model = ScriptedModel(script=[_domain("travel"), _pick("trip-organizer")])
    node = OrchestratorNode(model=model, registry=registry, catalog=catalog, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert catalog.searches >= 1
    assert result["route_decision"] == {"source": "model_classified", "agent_id": "trip-organizer"}
    assert sink.kinds() == ["route.classified"]


def test_two_hop_without_candidates_falls_back(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(
        model=ScriptedModel(script=[_domain("travel")]),
        registry=registry,
        catalog=_Catalog([]),
        orchestration=_spec(),
        audit_sink=sink,
    )
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert result["route_decision"]["fallback_reason"] == "main_agent_failed"
    assert sink.kinds() == ["route.default"]


def _with_document_extractor(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    _write_agent(agents, "budget-planner")
    _write_agent(agents / "_system", "document-extractor", hidden=True)
    return AgentRegistry(agents_dir=agents)


def test_builtin_document_route_is_recorded(tmp_path: Path) -> None:
    registry = _with_document_extractor(tmp_path)
    if registry.get("document-extractor") is None:
        pytest.skip("registry does not load system agents in this layout")
    sink = Sink()
    model = ScriptedModel(script=[])
    node = OrchestratorNode(model=model, registry=registry, default_agent="budget-planner", audit_sink=sink)
    result = asyncio.run(node.execute(_turn("read this", attachments=[{"mime_type": "application/pdf"}], turn_id="turn-d")))
    assert result["current_agent"] == "document-extractor"
    assert result["route_decision"] == {
        "source": "fixed_route",
        "route_id": BUILTIN_DOCUMENT_ROUTE_ID,
        "agent_id": "document-extractor",
    }
    assert sink.kinds() == ["route.fixed"]
    assert model.calls == 0


def test_route_source_values() -> None:
    assert RouteSource.MODEL_CLASSIFIED.value == "model_classified"


# ------------------------------------------------------------------ builder


def test_builder_can_leave_out_the_main_agent(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.builder import GraphBuilder

    model = ScriptedModel(script=[])
    with_main = GraphBuilder(model=model, registry=registry, orchestration=_spec()).build()
    without = GraphBuilder(model=model, registry=registry, orchestration=_spec(), include_main_agent=False).build()
    assert "main_agent" in with_main.get_graph().nodes
    assert "main_agent" not in without.get_graph().nodes


# ------------------------------------------------------------------ service


def _workspace(tmp_path: Path) -> Path:
    agents = tmp_path / "agents"
    _write_agent(agents, "budget-planner")
    _write_agent(agents, "trip-organizer")
    _write_agent(agents, "secret-helper", hidden=True)
    _write_agent(agents / "_system", "db-operator")
    return tmp_path


class _NeverRuns:
    def __init__(self) -> None:
        self.ran = False

    async def astream_events(self, *args: Any, **kwargs: Any) -> Any:
        self.ran = True
        raise AssertionError("the graph must not run for a refused pick")
        yield  # pragma: no cover

    async def astream(self, *args: Any, **kwargs: Any) -> Any:
        self.ran = True
        raise AssertionError("the graph must not run for a refused pick")
        yield  # pragma: no cover

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        self.ran = True
        raise AssertionError("the graph must not run for a refused pick")


async def _events(service: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    return [event async for event in service.execute_turn(**kwargs)]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id", ["secret-helper", "db-operator"])
async def test_service_refuses_a_hidden_pick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str) -> None:
    from yarvelle_core.config import settings
    from yarvelle_core.engine.service import AgentExecutionService

    import yarvelle_core.engine.service as service_module

    recorded: List[Any] = []

    async def capture(event: Any, **kwargs: Any) -> Any:
        recorded.append(event)
        return event

    monkeypatch.setattr(settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(service_module, "record_audit", capture)
    graph = _NeverRuns()
    service = AgentExecutionService(model=None, graph=graph, workspace_root=_workspace(tmp_path))
    events = await _events(service, thread_id=f"t-{agent_id}", prompt="hello", agent_id=agent_id)
    assert events and events[0]["type"] == "error"
    assert "cannot be picked directly" in events[0]["message"]
    assert not graph.ran
    rejected = [e for e in recorded if getattr(e, "event", None) == "route.rejected"]
    assert len(rejected) == 1 and rejected[0].agent_id == agent_id
    assert rejected[0].allowed is False and rejected[0].thread_id == f"t-{agent_id}"


@pytest.mark.asyncio
async def test_service_still_runs_a_visible_pick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_turn_routing_state import _Capture
    from yarvelle_core.config import settings
    from yarvelle_core.engine.service import AgentExecutionService

    monkeypatch.setattr(settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    capture = _Capture()
    service = AgentExecutionService(model=None, graph=capture.graph(), workspace_root=_workspace(tmp_path))
    await _events(service, thread_id="t-visible", prompt="hello", agent_id="trip-organizer")
    assert capture.inputs and capture.inputs[0]["explicit_agent"] == "trip-organizer"


def test_service_routes_only_with_a_spec(tmp_path: Path) -> None:
    from yarvelle_core.engine.service import AgentExecutionService

    plain = AgentExecutionService(model=None, workspace_root=tmp_path, default_agent_id="budget-planner")
    assert plain.routes_turns is False
    spec = PackOrchestrationSpec(default_agent="budget-planner")
    routed = AgentExecutionService(model=None, workspace_root=tmp_path, orchestration=spec)
    assert routed.routes_turns is True
    assert routed.default_agent_id == "budget-planner"
    # A caller's own graph always wins over the built-in one.
    assert AgentExecutionService(model=None, graph=object(), orchestration=spec).routes_turns is False


def test_service_builds_the_routing_graph_with_a_spec(tmp_path: Path) -> None:
    from yarvelle_core.engine.service import AgentExecutionService

    spec = PackOrchestrationSpec(default_agent="budget-planner")
    service = AgentExecutionService(model=None, workspace_root=_workspace(tmp_path), orchestration=spec)
    graph = service._build_execution_graph(ScriptedModel(script=[]), None, None)
    nodes = set(graph.get_graph().nodes)
    assert {"orchestrator", "main_agent"} <= nodes or {"supervisor", "main_agent"} <= nodes
    assert service._agent_registry().get("secret-helper") is not None


# ------------------------------------------------------------------ eval harness routing modes


@pytest.fixture()
def eval_pack(tmp_path: Path) -> Any:
    from tests.test_orch_eval_driver import write_pack
    from yarvelle_core.testing.orch_eval.pack import load_eval_pack

    return load_eval_pack(write_pack(tmp_path / "pack"))


def test_eval_hidden_pick_is_refused_and_routed(eval_pack: Any) -> None:
    from tests.test_orch_eval_driver import TRIP_TURN, run, scenario

    hidden = [a for a in eval_pack.hidden_ids]
    assert hidden, "the test pack needs a hidden agent"
    turn = {**TRIP_TURN, "explicit_agent": hidden[0]}
    result = run(eval_pack, scenario([turn]))
    assert result.passed, result.failures()
    trace = result.turns[0].trace
    assert trace.route == "main_agent"
    assert trace.route_events == ["route.rejected", "route.main_agent"]


def test_eval_classifier_route_is_audited(eval_pack: Any) -> None:
    from tests.test_orch_eval_driver import run, scenario

    turn = {
        "user": "Budget the weekend.",
        "expect": {"route": "model_classified", "agents_exactly": ["budget-planner"]},
        "fake": {"main": [{"route": "budget-planner"}], "agents": {"budget-planner": ["About 400."]}},
    }
    result = run(eval_pack, scenario([turn], routing="classifier"))
    assert result.passed, result.failures()
    assert result.turns[0].trace.route_events == ["route.classified"]


@pytest.mark.asyncio
async def test_service_routes_an_unpinned_turn_through_the_main_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yarvelle_core.engine.service as service_module
    from yarvelle_core.config import settings
    from yarvelle_core.engine.service import AgentExecutionService

    recorded: List[Any] = []

    async def capture(event: Any, **kwargs: Any) -> Any:
        recorded.append(event)
        return event

    monkeypatch.setattr(settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(service_module, "record_audit", capture)
    sink = Sink()
    spec = PackOrchestrationSpec(default_agent="budget-planner")
    model = ScriptedModel(script=[AIMessage(content="Here is a plan for your weekend.")])
    service = AgentExecutionService(model=model, workspace_root=_workspace(tmp_path), orchestration=spec)
    monkeypatch.setattr(
        service,
        "_build_orchestrated_graph",
        lambda active_model, checkpointer, store: _routing_graph(service, active_model, checkpointer, sink),
    )
    events = await _events(service, thread_id="t-routed", prompt="plan a weekend")
    assert not [e for e in events if e.get("type") == "error"], events
    assert "route.main_agent" in sink.kinds()
    assert "route.rejected" not in sink.kinds()


def _routing_graph(service: Any, model: Any, checkpointer: Any, sink: Sink) -> Any:
    """The service's routing graph with an in-memory route audit sink."""
    from yarvelle_core.engine.builder import GraphBuilder

    async def tasks(*args: Any, **kwargs: Any) -> None:
        return None

    return GraphBuilder(
        model=model,
        registry=service._agent_registry(),
        orchestration=service.orchestration,
        default_agent=service.default_agent_id,
        orchestration_audit_sink=sink,
        turn_task_sink=tasks,
        checkpointer=checkpointer,
    ).build(checkpointer=checkpointer)
