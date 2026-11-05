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

"""Unit tests for fault plans and the fault-injecting model wrapper."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from yarvelle_core.testing.orch_eval.faults import (
    DEFAULT_INJECT,
    FaultInjectingFakeModel,
    FaultPlan,
)
from yarvelle_core.testing.orch_eval.fake import ScriptedFakeChatModel
from yarvelle_core.testing.orch_eval.schema import FaultSpec, FakeScript


def _spec(**kwargs) -> FaultSpec:
    return FaultSpec.model_validate(kwargs)


def _inner() -> ScriptedFakeChatModel:
    model = ScriptedFakeChatModel()
    model.set_agents(["trip-organizer", "budget-planner", "writing-coach"])
    model.load_turn(1, FakeScript.model_validate({
        "main": [{"answer": "main-ok"}],
        "agents": {
            "trip-organizer": ["trip-ok"],
            "budget-planner": ["budget-ok"],
            "writing-coach": ["write-ok"],
        },
    }))
    return model


def _rm(**meta):
    tags = meta.pop("tags", [])
    return SimpleNamespace(metadata=meta, tags=tags)


def test_plan_separates_audit_and_cancel():
    plan = FaultPlan.from_specs([
        _spec(turn=1, agent="budget-planner", mode="error"),
        _spec(turn=1, mode="audit_error"),
        _spec(turn=1, cancel_after_ms=200),
    ])
    assert plan.audit_error is True
    assert plan.cancel_after_ms == 200
    assert plan.for_role("budget-planner").mode == "error"
    assert plan.for_role("main") is None


def test_star_matches_agents_not_main():
    plan = FaultPlan.from_specs([_spec(turn=1, agent="*", mode="slow", delay_s=1.0)])
    assert plan.for_role("trip-organizer") is not None
    assert plan.for_role("main") is None


def test_error_mode_raises_without_calling_inner():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["budget-planner"])
    wrapper.set_turn(1, FaultPlan.from_specs([_spec(turn=1, agent="budget-planner", mode="error", message="boom")]))
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="budget-planner")))


def test_after_calls_skips_first_invocation():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["writing-coach"])
    wrapper.set_turn(
        1,
        FaultPlan.from_specs([_spec(turn=1, agent="writing-coach", mode="error", after_calls=2)]),
    )
    first = asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="writing-coach")))
    assert first.generations[0].message.content == "write-ok"
    with pytest.raises(RuntimeError):
        asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="writing-coach")))


def test_inject_and_empty_and_garbage():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["trip-organizer", "budget-planner", "writing-coach"])

    wrapper.set_turn(1, FaultPlan.from_specs([_spec(turn=1, agent="trip-organizer", mode="empty")]))
    empty = asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="trip-organizer")))
    assert empty.generations[0].message.content == ""

    wrapper.set_turn(1, FaultPlan.from_specs([_spec(turn=1, agent="budget-planner", mode="garbage")]))
    garbage = asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="budget-planner")))
    assert "@@@" in garbage.generations[0].message.content

    wrapper.set_turn(1, FaultPlan.from_specs([_spec(turn=1, agent="writing-coach", mode="inject")]))
    injected = asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="writing-coach")))
    assert DEFAULT_INJECT in injected.generations[0].message.content


def test_truncate_returns_tool_call():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["trip-organizer"])
    wrapper.set_turn(
        1,
        FaultPlan.from_specs([_spec(turn=1, agent="trip-organizer", mode="truncate", tool="lookup_notes")]),
    )
    result = asyncio.run(
        wrapper._agenerate([HumanMessage(content="q")], run_manager=_rm(lc_agent_name="trip-organizer"))
    )
    msg = result.generations[0].message
    assert msg.tool_calls[0]["name"] == "lookup_notes"


def test_slow_then_inner_and_cancel_records_role():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["budget-planner"])
    wrapper.set_turn(
        1,
        FaultPlan.from_specs([_spec(turn=1, agent="budget-planner", mode="slow", delay_s=0.05)]),
    )
    result = asyncio.run(wrapper._agenerate([], run_manager=_rm(lc_agent_name="budget-planner")))
    assert result.generations[0].message.content == "budget-ok"

    wrapper.set_turn(
        1,
        FaultPlan.from_specs([_spec(turn=1, agent="budget-planner", mode="timeout", delay_s=2.0)]),
    )

    async def go():
        task = asyncio.create_task(wrapper._agenerate([], run_manager=_rm(lc_agent_name="budget-planner")))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert "budget-planner" in wrapper.cancelled


def test_suggestion_calls_bypass_faults():
    wrapper = FaultInjectingFakeModel(inner=_inner())
    wrapper.set_agents(["trip-organizer"])
    wrapper.set_turn(1, FaultPlan.from_specs([_spec(turn=1, agent="main", mode="error")]))
    # suggestion role is None -> no fault; inner still answers (as main exhausted or answer)
    # Load a suggestion-friendly inner path: ScriptedFake returns [] for suggestion.
    result = asyncio.run(wrapper._agenerate([], run_manager=_rm(tags=["suggestion"])))
    assert result.generations[0].message.content == "[]"


@pytest.mark.parametrize(
    "data",
    [
        {"turn": 1},
        {"turn": 1, "mode": "slow"},
        {"turn": 1, "agent": "x", "mode": "truncate"},
        {"turn": 1, "cancel_after_ms": 10, "mode": "error", "agent": "x"},
    ],
)
def test_fault_spec_rejects_bad_shapes(data):
    with pytest.raises(ValueError):
        FaultSpec.model_validate(data)
