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

"""Cancelled mid-route turns keep route_decision and current_agent on the checkpoint."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID
from yarvelle_core.testing.orch_eval.fake import ScriptedFakeChatModel
from yarvelle_core.testing.orch_eval.faults import FaultInjectingFakeModel, FaultPlan
from yarvelle_core.testing.orch_eval.pack import load_eval_pack
from yarvelle_core.testing.orch_eval.schema import FakeScript, FaultSpec

PACK_DIR = Path(__file__).resolve().parent.parent / "evals" / "orchestration" / "pack"


@pytest.fixture
def pack():
    return load_eval_pack(PACK_DIR)


def test_orchestrator_commits_main_agent_route_before_running(pack) -> None:
    from yarvelle_core.workflows.nodes import OrchestratorNode

    node = OrchestratorNode(
        model=ScriptedFakeChatModel(),
        registry=pack.registry,
        orchestration=pack.spec,
        main_agent_enabled=True,
    )
    result = asyncio.run(
        node.execute({"messages": [HumanMessage(content="plan")], "turn_id": "t1", "thread_id": "th"})
    )
    assert result["route_decision"] == {"source": "main_agent"}
    assert result["current_agent"] == MAIN_AGENT_ID
    assert result["next_step"] == MAIN_AGENT_ID


def test_cancel_mid_hand_off_keeps_route_on_checkpoint(pack) -> None:
    """User cancel after hand-offs start must leave route_decision on state."""
    model = ScriptedFakeChatModel()
    model.set_agents(pack.agent_ids)
    model.load_turn(
        1,
        FakeScript.model_validate(
            {
                "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "never"}],
                "agents": {"trip-organizer": ["x"], "budget-planner": ["y"]},
            }
        ),
    )
    fault = FaultInjectingFakeModel(inner=model)
    fault.set_agents(pack.agent_ids)
    fault.set_turn(
        1,
        FaultPlan.from_specs(
            [FaultSpec.model_validate({"turn": 1, "agent": "*", "mode": "slow", "delay_s": 8})]
        ),
    )

    audit: List[Any] = []

    async def audit_sink(event: Any) -> None:
        audit.append(event)

    async def turn_task_sink(rows):
        return None

    graph = GraphBuilder(
        model=fault,
        registry=pack.registry,
        orchestration=pack.spec,
        include_main_agent=True,
        orchestration_audit_sink=audit_sink,
        turn_task_sink=turn_task_sink,
        safety_policy=pack.safety_policy(),
        checkpointer=MemorySaver(),
    ).build()

    thread_id = f"cancel-route-{uuid.uuid4().hex[:8]}"
    config: Dict[str, Any] = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    state_in = {
        "messages": [HumanMessage(content="Plan a trip and a budget.")],
        "thread_id": thread_id,
    }

    async def scenario() -> None:
        task = asyncio.create_task(graph.ainvoke(state_in, config=config))

        async def cancel_when_started() -> None:
            deadline = time.perf_counter() + 8.0
            while time.perf_counter() < deadline:
                if any(str(getattr(e, "event", "")).startswith("task.started") for e in audit):
                    await asyncio.sleep(0.05)
                    break
                await asyncio.sleep(0.01)
            if not task.done():
                task.cancel()

        watchdog = asyncio.create_task(cancel_when_started())
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    asyncio.run(scenario())
    after = asyncio.run(graph.aget_state(config))
    values = dict(after.values or {}) if after is not None else {}
    decision = values.get("route_decision")
    assert decision is not None, f"route_decision missing after cancel; keys={sorted(values)}"
    assert decision.get("source") == "main_agent", decision
    assert values.get("current_agent") == MAIN_AGENT_ID
    assert any(str(getattr(e, "event", "")) == "route.main_agent" for e in audit)
