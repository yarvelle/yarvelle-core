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

"""Per-turn routing state, route audit records and guardrail flags.

Regression tests for three routing bugs: routing results leaking into the
next turn on one thread, route audit records written only by the main-agent
router, and fixed routes on a guardrail flag that never fired because nothing
raised the flag. All models are in-process fakes; nothing calls a real model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from tests.test_hybrid_routing import Sink, _spec, _turn, _write_agent
from tests.test_orch_eval_driver import TRIP_TURN, run, scenario, write_pack
from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.safety_policy import NeutralSafetyPolicy, UnionSafetyPolicy, policy_flags
from yarvelle_core.testing.orch_eval.pack import EvalPack, KeywordFlagPolicy, load_eval_pack
from yarvelle_core.workflows.nodes import InputGuardrailNode, OrchestratorNode
from yarvelle_core.workflows.state import (
    TURN_INPUT_FIELDS,
    TURN_OUTPUT_DEFAULTS,
    AgentState,
    turn_end_values,
    turn_start_values,
)


@pytest.fixture()
def pack(tmp_path: Path) -> EvalPack:
    return load_eval_pack(write_pack(tmp_path / "pack"))


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    for agent_id in ("budget-planner", "trip-organizer", "doc-reader"):
        _write_agent(agents, agent_id)
    _write_agent(agents, "secret-helper", hidden=True)
    return AgentRegistry(agents_dir=agents)


def _traces(result: Any) -> List[Any]:
    return [t.trace for t in result.turns]


# ------------------------------------------------------------------ state helpers


def test_turn_start_values_reset_outputs_and_pin_only_the_callers_pick() -> None:
    fresh = turn_start_values("turn-7", None)
    assert fresh["turn_id"] == "turn-7"
    assert fresh["current_agent"] is None
    for key, value in TURN_OUTPUT_DEFAULTS.items():
        assert fresh[key] == value
    assert turn_start_values(explicit_agent="budget-planner")["current_agent"] == "budget-planner"
    # Each turn gets its own containers and its own id.
    other = turn_start_values()
    assert other["orchestration_notices"] is not fresh["orchestration_notices"]
    assert other["turn_id"] and other["turn_id"] != turn_start_values()["turn_id"]


def test_turn_end_values_drop_one_turn_caller_choices() -> None:
    assert turn_end_values() == {k: None for k in TURN_INPUT_FIELDS}
    assert set(TURN_INPUT_FIELDS) == {"explicit_agent", "execution_plan"}


def test_explicit_agent_and_turn_id_are_graph_state() -> None:
    # Keys missing from AgentState are dropped from graph input.
    assert {"explicit_agent", "turn_id"} <= set(AgentState.__annotations__)


# ------------------------------------------------------------------ fix 1: no leaks across turns


def test_user_selected_pin_does_not_stick_to_the_next_turn(pack: EvalPack) -> None:
    pinned = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "expect": {"route": "user_selected", "agents_exactly": ["writing-coach"]},
        "fake": {"agents": {"writing-coach": ["Here is your note, fixed."]}},
    }
    result = run(pack, scenario([pinned, TRIP_TURN]))
    assert result.passed, result.failures()
    first, second = _traces(result)
    assert first.route == "user_selected" and first.route_agent == "writing-coach"
    assert second.route == "main_agent"
    assert second.route_events == ["route.main_agent"]


def test_routing_results_reset_each_turn(pack: EvalPack) -> None:
    pinned = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "expect": {"route": "user_selected", "notices": []},
        "fake": {"agents": {"writing-coach": ["Fixed."]}},
    }
    result = run(pack, scenario([TRIP_TURN, pinned]))
    assert result.passed, result.failures()
    first, second = _traces(result)
    assert first.provenance and first.turn_tasks
    # Turn two ran no hand-off: no provenance, notices or turn tasks carry over.
    assert second.provenance == [] and second.notices == [] and second.turn_tasks == []
    assert second.route == "user_selected"


def test_notices_do_not_pile_up_across_turns(pack: EvalPack) -> None:
    partial = {
        "user": "Plan and budget.",
        "expect": {"notices": [{"code": "partial_failure", "agent_ids": ["budget-planner"]}]},
        "fake": {
            "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "Trip is ready."}],
            "agents": {"trip-organizer": ["Two nights."], "budget-planner": [{"error": "down"}]},
        },
    }
    clean = {**TRIP_TURN, "expect": {**TRIP_TURN["expect"], "notices": []}}
    result = run(pack, scenario([partial, clean, partial]))
    assert result.passed, result.failures()
    codes = [[n["code"] for n in t.notices] for t in _traces(result)]
    assert codes == [["partial_failure"], [], ["partial_failure"]]


def test_orchestrator_fallback_does_not_mutate_state_notices(registry: AgentRegistry) -> None:
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec())
    earlier: List[Dict[str, Any]] = []
    state = _turn("plan a weekend", orchestration_notices=earlier, turn_id="turn-1")
    result = asyncio.run(node.execute(state))
    assert earlier == []
    assert [n["code"] for n in result["orchestration_notices"]] == ["model_unavailable"]
    assert result["orchestration_notices"][0]["turn_id"] == "turn-1"


def test_execution_plan_is_plain_json(registry: AgentRegistry) -> None:
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec())
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert type(result["execution_plan"]["mode"]) is str


# ------------------------------------------------------------------ fix 1: the service does not pin


class _Capture:
    def __init__(self) -> None:
        self.inputs: List[Dict[str, Any]] = []

    def graph(self) -> Any:
        async def node(state: AgentState) -> Dict[str, Any]:
            self.inputs.append(dict(state))
            return {}

        builder = StateGraph(AgentState)
        builder.add_node("capture", node)
        builder.add_edge(START, "capture")
        builder.add_edge("capture", END)
        return builder.compile()


async def _turn_input(agent_id: Optional[str]) -> Dict[str, Any]:
    from yarvelle_core.engine.service import AgentExecutionService

    capture = _Capture()
    service = AgentExecutionService(model=None, graph=capture.graph(), default_agent_id="orchestrator")
    kwargs: Dict[str, Any] = {"thread_id": f"t-{agent_id or 'none'}", "prompt": "hello"}
    if agent_id:
        kwargs["agent_id"] = agent_id
    async for _ in service.execute_turn(**kwargs):
        pass
    assert capture.inputs, "the graph never ran"
    return capture.inputs[0]


@pytest.mark.asyncio
async def test_service_leaves_unpinned_turns_to_the_router() -> None:
    state = await _turn_input(None)
    assert state.get("current_agent") is None
    assert state.get("explicit_agent") is None
    assert state.get("agent_id") == "orchestrator"


@pytest.mark.asyncio
async def test_service_pins_only_an_explicit_pick() -> None:
    state = await _turn_input("orchestrator")
    assert state.get("current_agent") == "orchestrator"
    assert state.get("explicit_agent") == "orchestrator"


# ------------------------------------------------------------------ fix 2: route audit for every route


def test_user_selected_route_is_audited(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn(explicit_agent="trip-organizer", turn_id="turn-u", thread_id="th-1")))
    assert result["route_decision"] == {"source": "user_selected", "agent_id": "trip-organizer"}
    assert sink.kinds() == ["route.user_selected"]
    event = sink.events[0]
    assert event.agent_id == "trip-organizer" and event.turn_id == "turn-u" and event.thread_id == "th-1"
    assert event.details == {"route": {"source": "user_selected", "agent_id": "trip-organizer"}}


def test_fixed_route_is_audited_by_the_orchestrator(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn(attachments=[{"mime_type": "application/pdf"}], turn_id="turn-f")))
    assert result["route_decision"]["source"] == "fixed_route"
    assert sink.kinds() == ["route.fixed"]
    assert sink.events[0].turn_id == "turn-f" and sink.events[0].agent_id == "doc-reader"


def test_default_fallback_is_audited_with_a_decision(registry: AgentRegistry) -> None:
    sink = Sink()
    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=sink)
    result = asyncio.run(node.execute(_turn("plan a weekend")))
    assert result["route_decision"] == {
        "source": "default_agent",
        "agent_id": "budget-planner",
        "fallback_reason": "model_unavailable",
    }
    assert sink.kinds() == ["route.default"]


def test_route_audit_failure_stops_the_turn(registry: AgentRegistry) -> None:
    from yarvelle_core.engine.orchestration.task_guard import OrchestrationAuditError

    async def broken(event: Any) -> None:
        raise OSError("disk full")

    node = OrchestratorNode(model=None, registry=registry, orchestration=_spec(), audit_sink=broken)
    with pytest.raises(OrchestrationAuditError):
        asyncio.run(node.execute(_turn(explicit_agent="trip-organizer")))


def test_every_eval_route_has_its_audit_record(pack: EvalPack) -> None:
    pinned = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "expect": {"route": "user_selected"},
        "fake": {"agents": {"writing-coach": ["Fixed."]}},
    }
    urgent = {
        "user": "Urgent: I am locked out.",
        "input": {"guardrail_flag": "urgent"},
        "expect": {"route": "fixed_route:urgent"},
        "fake": {"agents": {"escalation-desk": ["Call the front desk."]}},
    }
    result = run(pack, scenario([pinned, urgent, TRIP_TURN]))
    assert result.passed, result.failures()
    assert [t.route_events for t in _traces(result)] == [["route.user_selected"], ["route.fixed"], ["route.main_agent"]]


# ------------------------------------------------------------------ fix 3: flags from the input


class _Flags(NeutralSafetyPolicy):
    def __init__(self, flags: Sequence[str]) -> None:
        self.flags = list(flags)

    def check_flags(self, text: Optional[str], ctx: Any = None) -> List[str]:
        return list(self.flags)


def test_policy_flags_normalise_and_skip_policies_without_flags() -> None:
    class Legacy:
        pass

    assert policy_flags(Legacy(), "anything") == []
    assert policy_flags(_Flags(["Urgent", "urgent", "not a slug!", ""]), "x") == ["urgent"]
    union = UnionSafetyPolicy([_Flags(["urgent"]), NeutralSafetyPolicy(), _Flags(["night", "urgent"])])
    assert union.check_flags("x") == ["urgent", "night"]


def test_keyword_flag_policy_matches_whole_words() -> None:
    policy = KeywordFlagPolicy({"urgent": ["urgent", "stuck"]})
    assert policy.check_flags("I am STUCK here") == ["urgent"]
    assert policy.check_flags("Unstuck now, thanks") == []


def test_input_guardrail_raises_flags_from_the_text() -> None:
    node = InputGuardrailNode(safety_policy=KeywordFlagPolicy({"urgent": ["urgent"]}))
    raised = asyncio.run(node.execute({"messages": [HumanMessage(content="This is urgent.")]}))
    assert raised["guardrail_flags"] == ["urgent"]
    # Flags come from this turn's text only; a stale flag is replaced.
    calm = asyncio.run(node.execute({"messages": [HumanMessage(content="Plan lunch.")], "guardrail_flags": ["urgent"]}))
    assert calm["guardrail_flags"] == []


def test_urgent_text_takes_the_fixed_route_with_no_model_call(pack: EvalPack) -> None:
    urgent = {
        "user": "Urgent: the hotel lost my booking.",
        "input": {"guardrail_flag": "urgent"},
        "expect": {"route": "fixed_route:urgent", "agents_exactly": ["escalation-desk"], "model_calls_before_route": 0},
        "fake": {"agents": {"escalation-desk": ["Ask the front desk for the manager."]}},
    }
    result = run(pack, scenario([urgent, TRIP_TURN]))
    assert result.passed, result.failures()
    first, second = _traces(result)
    assert first.guardrail_flags == ["urgent"] and second.guardrail_flags == []


def test_text_without_the_flag_word_routes_normally(pack: EvalPack) -> None:
    result = run(pack, scenario([{**TRIP_TURN, "user": "Plan a weekend and budget it, no rush."}]))
    assert result.passed, result.failures()
    assert _traces(result)[0].guardrail_flags == []
