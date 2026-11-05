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

"""Main-agent replies: synthesis instructions, provenance and stated gaps.

Every model here is a scripted in-process fake; nothing calls a real model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from tests.test_task_call_hardening import MAIN, AgentScriptedModel, Sink, _tasks, _write_agent
from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.orchestration import HybridRouter
from yarvelle_core.engine.orchestration.runtime import (
    MAIN_AGENT_PROMPT,
    build_provenance,
    compose_main_prompt,
    gap_statement,
    state_gaps,
)
from yarvelle_core.engine.orchestration.task_guard import TaskRun
from yarvelle_core.schemas.audit import AuditEvent
from yarvelle_core.schemas.orchestration import (
    OrchestrationLimits,
    PackOrchestrationSpec,
    SynthesisSpec,
    TaskProvenance,
)
from yarvelle_core.workflows.nodes import main_agent_node as main_agent_module
from yarvelle_core.workflows.nodes import response_synthesizer_node as synth_module
from yarvelle_core.workflows.nodes.main_agent_node import MainAgentNode
from yarvelle_core.workflows.nodes.response_synthesizer_node import CANONICAL_DISCLAIMER, ResponseSynthesizerNode

AGENT_IDS = ("budget-planner", "trip-organizer", "doc-reader")


class PromptRecordingModel(AgentScriptedModel):
    """Scripted fake that also keeps the main agent's system prompts."""

    main_prompts: List[str] = []

    async def _reply(self, messages: List[BaseMessage]) -> BaseMessage:
        if self._who(messages) == MAIN:
            system = next((m for m in messages if isinstance(m, SystemMessage)), None)
            self.main_prompts.append(str(system.content) if system is not None else "")
        return await super()._reply(messages)


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    for agent_id in AGENT_IDS:
        _write_agent(agents, agent_id)
    return AgentRegistry(agents_dir=agents)


def _spec(instructions: str = "", **limits: Any) -> PackOrchestrationSpec:
    return PackOrchestrationSpec(
        default_agent="budget-planner",
        limits=OrchestrationLimits(**limits),
        synthesis=SynthesisSpec(instructions=instructions),
    )


def _turn() -> Dict[str, Any]:
    return {"messages": [HumanMessage(content="plan my week")]}


def _assert_no_slugs(text: str) -> None:
    for agent_id in AGENT_IDS:
        assert agent_id not in text, f"agent id {agent_id!r} leaked into user-facing text"


# ------------------------------------------------------------------ synthesis instructions


@pytest.mark.asyncio
async def test_pack_synthesis_instructions_reach_the_main_agent_prompt(registry: AgentRegistry) -> None:
    model = PromptRecordingModel(scripts={MAIN: [AIMessage(content="Done.")]}, main_prompts=[])
    spec = _spec("Lead with a one-line summary, then a short list.")
    router = HybridRouter(registry=registry, model=model, spec=spec)
    await router.run(_turn())
    assert model.main_prompts, "the main agent never called the model"
    prompt = model.main_prompts[0]
    assert prompt.startswith(MAIN_AGENT_PROMPT)
    assert "How to compose the reply:\nLead with a one-line summary, then a short list." in prompt


def test_compose_main_prompt_without_instructions_is_the_base_prompt() -> None:
    assert compose_main_prompt() == MAIN_AGENT_PROMPT
    assert compose_main_prompt(None, SynthesisSpec(instructions="   ")) == MAIN_AGENT_PROMPT
    assert compose_main_prompt("Custom base.", SynthesisSpec(instructions="Be brief.")).startswith("Custom base.")


def test_synthesis_spec_is_optional_and_strict() -> None:
    assert PackOrchestrationSpec(default_agent="budget-planner").synthesis.instructions == ""
    with pytest.raises(ValueError):
        PackOrchestrationSpec.model_validate({"default_agent": "budget-planner", "synthesis": {"template": "x"}})


# ------------------------------------------------------------------ provenance


@pytest.mark.asyncio
async def test_provenance_matches_task_ids_and_audit_records(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "t-budget"), ("trip-organizer", "t-trip")), AIMessage(content="Your week is set.")],
            "budget-planner": [AIMessage(content="Spend 200.")],
            "trip-organizer": [AIMessage(content="Leave Monday.")],
        },
    )
    sink = Sink()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=sink)
    outcome = await router.run(_turn())
    assert outcome is not None

    assert [p.task_id for p in outcome.provenance] == ["t-budget", "t-trip"]
    assert [p.task_id for p in outcome.provenance] == [r.task_id for r in outcome.tasks]
    by_task = {p.task_id: p for p in outcome.provenance}
    assert by_task["t-budget"].agent_id == "budget-planner"
    assert by_task["t-budget"].agent_title == "Budget Planner"
    assert by_task["t-trip"].agent_title == "Trip Organizer"

    completed = {str(e.task_id): e for e in sink.events if e.event == "task.completed"}
    for entry in outcome.provenance:
        assert entry.state == "completed"
        assert entry.output_hash == completed[entry.task_id].output_hash
        # The subagent run that answered reported the same agent name.
        assert entry.verified is True
    assert outcome.messages[-1].content == "Your week is set."


@pytest.mark.asyncio
async def test_main_agent_node_returns_provenance(registry: AgentRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _quiet(name: str, payload: Dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(main_agent_module, "_dispatch", _quiet)
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("trip-organizer", "only")), AIMessage(content="Trip is planned.")],
            "trip-organizer": [AIMessage(content="Leave Monday.")],
        },
    )
    node = MainAgentNode(model=model, registry=registry, orchestration=_spec(), status_sink=lambda _p: None)
    result = await node.execute(_turn())
    assert [p["task_id"] for p in result["provenance"]] == ["only"]
    TaskProvenance.model_validate(result["provenance"][0])


def test_build_provenance_prefers_the_terminal_audit_record() -> None:
    runs = [TaskRun(agent_id="budget-planner", task_id="x", state="started", lc_agent_name="someone-else")]
    records = [
        AuditEvent(event="task.started", agent_id="budget-planner", turn_id="t", task_id="x"),
        AuditEvent(event="task.timed_out", agent_id="budget-planner", turn_id="t", task_id="x"),
    ]
    (entry,) = build_provenance(runs, records, {"budget-planner": "Budget Planner"})
    assert entry.state == "timed_out"
    assert entry.verified is False  # reported name differs from the requested agent


# ------------------------------------------------------------------ gaps are stated


@pytest.mark.asyncio
async def test_failed_agent_is_named_in_the_reply(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content="Here is the trip.")],
            "trip-organizer": [AIMessage(content="Leave Monday.")],
        },
        failures=["budget-planner"],
    )
    router = HybridRouter(registry=registry, model=model, spec=_spec())
    outcome = await router.run(_turn())
    assert outcome is not None
    answer = str(outcome.messages[-1].content)
    assert answer.startswith("Here is the trip.")
    assert "Budget Planner did not answer" in answer
    assert "Trip Organizer" not in answer
    assert {p.task_id: p.state for p in outcome.provenance} == {"b": "failed", "t": "completed"}
    _assert_no_slugs(answer)


@pytest.mark.asyncio
async def test_reply_that_already_names_the_gap_is_left_alone(registry: AgentRegistry) -> None:
    reply = "Budget Planner could not help this time; here is the trip."
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content=reply)],
            "trip-organizer": [AIMessage(content="Leave Monday.")],
        },
        failures=["budget-planner"],
    )
    outcome = await HybridRouter(registry=registry, model=model, spec=_spec()).run(_turn())
    assert outcome is not None and outcome.messages[-1].content == reply


@pytest.mark.asyncio
async def test_timed_out_and_truncated_agents_are_named(tmp_path: Path) -> None:
    from langchain_core.tools import tool

    @tool
    def lookup(query: str) -> str:
        """Looks something up."""
        return "more"

    agents = tmp_path / "agents"
    _write_agent(agents, "doc-reader", max_iterations=1)
    _write_agent(agents, "budget-planner")
    registry = AgentRegistry(
        agents_dir=agents, tool_resolver=lambda manifest, names: [lookup] if manifest.id == "doc-reader" else []
    )
    loop = [
        AIMessage(content="", tool_calls=[{"name": "lookup", "id": f"l{i}", "args": {"query": "x"}}]) for i in range(5)
    ]
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("doc-reader", "d"), ("budget-planner", "b")), AIMessage(content="Partial answer.")],
            "doc-reader": loop,
            "budget-planner": [AIMessage(content="late")],
        },
        delays={"budget-planner": 5.0},
    )
    router = HybridRouter(registry=registry, model=model, spec=_spec(agent_timeout_s=0.3, turn_timeout_s=10))
    outcome = await router.run(_turn())
    assert outcome is not None
    answer = str(outcome.messages[-1].content)
    assert "Budget Planner did not answer" in answer
    assert "Doc Reader stopped early" in answer
    by_task = {p.task_id: p for p in outcome.provenance}
    assert by_task["d"].truncated and by_task["d"].state == "completed"
    assert by_task["b"].state == "timed_out"
    _assert_no_slugs(answer)


def test_gap_statement_is_none_when_every_agent_answered() -> None:
    ok = TaskProvenance(task_id="a", agent_id="budget-planner", agent_title="Budget Planner", state="completed")
    assert gap_statement([ok]) is None
    msgs: List[BaseMessage] = [AIMessage(content="All good.")]
    assert state_gaps(msgs, [ok]) == msgs


def test_gap_statement_without_an_answer_adds_one() -> None:
    failed = TaskProvenance(task_id="a", agent_id="budget-planner", agent_title="Budget Planner", state="failed")
    out = state_gaps([ToolMessage(content="x", tool_call_id="a")], [failed])
    assert isinstance(out[-1], AIMessage) and "Budget Planner did not answer" in str(out[-1].content)


# ------------------------------------------------------------------ no slug leaks


@pytest.mark.asyncio
async def test_no_agent_ids_reach_user_facing_text(registry: AgentRegistry) -> None:
    model = AgentScriptedModel(
        scripts={
            MAIN: [_tasks(("budget-planner", "b"), ("trip-organizer", "t")), AIMessage(content="Here is what I have.")],
            "trip-organizer": [AIMessage(content="late")],
        },
        failures=["budget-planner"],
        delays={"trip-organizer": 5.0},
    )
    router = HybridRouter(registry=registry, model=model, spec=_spec(agent_timeout_s=0.3, turn_timeout_s=10))
    outcome = await router.run(_turn())
    assert outcome is not None
    _assert_no_slugs(str(outcome.messages[-1].content))
    for notice in outcome.notices:
        _assert_no_slugs(notice.message)
    # Error results handed back to the main agent name agents by title too.
    for message in outcome.messages:
        if isinstance(message, ToolMessage) and message.status == "error":
            _assert_no_slugs(str(message.content))


def test_synthesizer_has_no_pattern_heuristics_or_slug_titles() -> None:
    for name in ("strip_disclaimers", "strip_reference_preamble"):
        assert not hasattr(ResponseSynthesizerNode, name)
    assert not hasattr(synth_module, "CONSTITUENT_DISCLAIMER_PATTERNS")

    state = {
        "specialist_outputs": {"budget-planner": "Spend 200.", "trip-organizer": "Leave Monday."},
        "agent_titles": {"budget-planner": "Budget Planner", "trip-organizer": "Trip Organizer"},
    }
    out = ResponseSynthesizerNode.synthesize_response(state)
    assert "Budget Planner" in out and "Trip Organizer" in out
    assert "Multi-Agent Coordination Summary" not in out and "Perspective" not in out
    _assert_no_slugs(out)
    assert out.count(CANONICAL_DISCLAIMER) == 1


def test_synthesizer_passes_a_composed_answer_through() -> None:
    state = {
        "messages": [HumanMessage(content="hi"), AIMessage(content=f"Composed reply.\n\n{CANONICAL_DISCLAIMER}")],
        "specialist_outputs": {"budget-planner": "Spend 200.", "trip-organizer": "Leave Monday."},
    }
    out = ResponseSynthesizerNode.synthesize_response(state)
    assert out == f"Composed reply.\n\n{CANONICAL_DISCLAIMER}"
