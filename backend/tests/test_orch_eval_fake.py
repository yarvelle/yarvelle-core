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

"""Unit tests for the scripted fake model and fake backend."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from yarvelle_core.testing.orch_eval.backends import EvalBackend, Role
from yarvelle_core.testing.orch_eval.fake import FakeBackend, FakeScriptError, ScriptedFakeChatModel
from yarvelle_core.testing.orch_eval.schema import FakeScript


def _script(data: dict) -> FakeScript:
    return FakeScript.model_validate(data)


def _model() -> ScriptedFakeChatModel:
    model = ScriptedFakeChatModel()
    model.set_agents(["trip-organizer", "budget-planner"])
    return model


def _rm(**meta):
    return SimpleNamespace(metadata=meta, tags=meta.pop("tags", []))


def test_backend_satisfies_protocol_and_is_free():
    backend = FakeBackend()
    assert isinstance(backend, EvalBackend)
    assert backend.cost_per_mtok.is_free
    assert backend.model_for(Role(kind="main")) is backend.model_for(Role(kind="agent", agent_id="x"))
    assert "key" not in str(backend.describe()).lower()


def test_main_task_step_builds_task_calls():
    model = _model()
    model.load_turn(1, _script({"main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "done"}]}))
    msg = model._reply([HumanMessage(content="plan it")], _rm(lc_agent_name="main-agent"))
    assert [c["args"]["subagent_type"] for c in msg.tool_calls] == ["trip-organizer", "budget-planner"]
    assert len({c["id"] for c in msg.tool_calls}) == 2
    assert model._reply([], _rm(lc_agent_name="main-agent")).content == "done"
    assert model.problems(1) == []


def test_roles_from_metadata_then_persona_marker():
    model = _model()
    model.load_turn(1, _script({"agents": {"trip-organizer": ["by name"], "budget-planner": ["by marker"]}}))
    assert model._reply([], _rm(lc_agent_name="trip-organizer")).content == "by name"
    persona = [SystemMessage(content="You are the budget-planner agent.\nHelps.")]
    assert model._reply(persona, _rm()).content == "by marker"


def test_suggestion_calls_do_not_consume_the_script():
    model = _model()
    model.load_turn(1, _script({"main": [{"answer": "kept"}]}))
    assert model._reply([], _rm(tags=["internal", "suggestion"])).content == "[]"
    assert model.unused_steps() == {"__main__": 1}


def test_error_step_raises_and_exhaustion_is_reported():
    model = _model()
    model.load_turn(2, _script({"agents": {"trip-organizer": [{"error": "down"}]}, "main": [{"answer": "a"}, {"answer": "b"}]}))
    with pytest.raises(FakeScriptError):
        model._reply([], _rm(lc_agent_name="trip-organizer"))
    model._reply([], _rm(lc_agent_name="trip-organizer"))
    problems = model.problems(2)
    assert any("trip-organizer was called with no scripted reply left" in p for p in problems)
    assert any("__main__ has 2 unused" in p for p in problems)


def test_tool_step_calls_named_tool():
    model = _model()
    model.load_turn(1, _script({"agents": {"trip-organizer": [{"tool": "lookup_notes"}]}}))
    msg = model._reply([HumanMessage(content="q")], _rm(lc_agent_name="trip-organizer"))
    assert msg.tool_calls[0]["name"] == "lookup_notes"


def test_load_turn_replaces_queues():
    model = _model()
    model.load_turn(1, _script({"main": [{"answer": "one"}]}))
    model.load_turn(2, None)
    assert model.unused_steps() == {}


def test_async_stream_yields_tool_call_chunks():
    model = _model()
    model.load_turn(1, _script({"main": [{"task": ["trip-organizer"]}]}))

    async def go():
        return [c async for c in model._astream([], run_manager=None)]

    chunks = asyncio.run(go())
    assert chunks[0].message.tool_call_chunks[0]["name"] == "task"


@pytest.mark.parametrize(
    "step",
    [{}, {"task": ["a"], "answer": "x"}, {"answer": "x", "error": "y"}],
)
def test_main_step_needs_exactly_one_kind(step):
    with pytest.raises(ValueError):
        FakeScript.model_validate({"main": [step]})


@pytest.mark.parametrize("step", [{}, {"error": "x", "tool": "t"}, {"tool": "Bad-Name"}])
def test_agent_step_needs_exactly_one_kind(step):
    with pytest.raises(ValueError):
        FakeScript.model_validate({"agents": {"a": [step]}})
