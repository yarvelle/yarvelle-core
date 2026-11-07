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

"""A refused main-agent answer ends on the refusal path (#39).

Before the fix the reflection retry sent the turn to the single-agent node
with ``current_agent="main-agent"``, which is not a registered agent, and the
user saw "Unknown or unregistered agent ID: 'main-agent'".
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID
from yarvelle_core.engine.safety_policy import SafetyVerdict
from yarvelle_core.testing.orch_eval.driver import ScenarioRunner
from yarvelle_core.testing.orch_eval.fake import FakeBackend
from yarvelle_core.testing.orch_eval.pack import EvalPack, KeywordFlagPolicy, load_eval_pack
from yarvelle_core.workflows.nodes.base import BaseNode
from yarvelle_core.workflows.nodes.reflection_node import ReflectionNode

from tests.test_orch_eval_driver import scenario, write_pack

UNSAFE = "Unsafe answer: do the risky thing now."
CORE_REFUSAL_MARK = "informational navigation assistant"


class _OutputPolicy(KeywordFlagPolicy):
    """Refuses any answer that starts with "Unsafe answer"."""

    def check_output(self, text: Optional[str], ctx: Any = None) -> SafetyVerdict:
        if (text or "").startswith("Unsafe answer"):
            return SafetyVerdict(refused=True, reason="forbidden_intent:policy_prohibited")
        return SafetyVerdict(refused=False)


class LegacyReflectionNode(BaseNode):
    """A pack's reflection node written before the fix: always asks for 'agent'."""

    def __init__(self) -> None:
        super().__init__(name="reflection")

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {"reflection_count": int(state.get("reflection_count", 0)) + 1, "next_step": "agent"}


class RefusingReflectionNode(BaseNode):
    """A pack's reflection node that ends main-agent turns itself (the old workaround)."""

    def __init__(self) -> None:
        super().__init__(name="reflection")

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if state.get("current_agent") == MAIN_AGENT_ID:
            return {"next_step": "refusal"}
        return {"reflection_count": int(state.get("reflection_count", 0)) + 1, "next_step": "agent"}


def _pack(tmp_path: Path) -> EvalPack:
    base = load_eval_pack(write_pack(tmp_path / "pack"))

    @dataclasses.dataclass(frozen=True)
    class _Pack(EvalPack):
        def safety_policy(self) -> KeywordFlagPolicy:
            return _OutputPolicy(self.flag_words)

    return _Pack(**{f.name: getattr(base, f.name) for f in dataclasses.fields(base)})


class _RunnerWithReflection(ScenarioRunner):
    """Builds the eval graph with a pack's own reflection node, as a pack does
    in production with ``GraphBuilder.with_node("reflection", ...)``."""

    reflection: type = ReflectionNode

    def _build_graph(self, scenario: Any, spec: Any, model: Any, audit: Any, turn_tasks: Any, checkpointer: Any) -> Any:
        from yarvelle_core.engine.builder import GraphBuilder

        return (
            GraphBuilder(
                model=model,
                registry=self.pack.registry,
                orchestration=spec,
                default_agent=spec.default_agent,
                include_main_agent=True,
                orchestration_audit_sink=audit,
                turn_task_sink=turn_tasks,
                safety_policy=self.pack.safety_policy(),
                checkpointer=checkpointer,
            )
            .with_node("reflection", self.reflection())
            .build()
        )


def _run(pack: EvalPack, turns: list, reflection: Optional[type] = None) -> Any:
    if reflection is None:
        runner: ScenarioRunner = ScenarioRunner(pack, FakeBackend())
    else:
        runner = type("_Runner", (_RunnerWithReflection,), {"reflection": reflection})(pack, FakeBackend())
    return asyncio.run(runner.run(scenario(turns)))


MAIN_UNSAFE = {
    "user": "Plan a weekend.",
    "expect": {"route": "main_agent", "answer": {"must_not_mention": ["Unsafe answer", "main-agent", "Unknown or unregistered"]}},
    "fake": {"main": [{"answer": UNSAFE}]},
}


def _assert_safe_refusal(result: Any) -> None:
    trace = result.turns[0].trace
    assert trace.error is None, trace.error
    assert "agent" not in trace.nodes, trace.nodes
    assert "refusal" in trace.nodes, trace.nodes
    assert CORE_REFUSAL_MARK in trace.answer
    assert "Unknown or unregistered agent" not in trace.answer
    assert UNSAFE not in trace.answer


def test_refused_main_agent_answer_gets_the_refusal(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path), [MAIN_UNSAFE])
    _assert_safe_refusal(result)
    assert result.passed, result.failures()


def test_legacy_pack_reflection_node_cannot_send_main_agent_to_agent_node(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path), [MAIN_UNSAFE], LegacyReflectionNode)
    _assert_safe_refusal(result)


def test_pack_reflection_node_that_refuses_still_works(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path), [MAIN_UNSAFE], RefusingReflectionNode)
    _assert_safe_refusal(result)


def test_refused_specialist_answer_is_still_retried(tmp_path: Path) -> None:
    turn = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "expect": {"route": "user_selected", "agents_exactly": ["writing-coach"]},
        "fake": {"agents": {"writing-coach": [UNSAFE, "Here is your note, fixed."]}},
    }
    result = _run(_pack(tmp_path), [turn])
    trace = result.turns[0].trace
    assert trace.error is None, trace.error
    assert "reflection" in trace.nodes and "refusal" not in trace.nodes
    assert trace.answer == "Here is your note, fixed."
    assert result.passed, result.failures()


@pytest.mark.asyncio
async def test_reflection_node_does_not_retry_a_main_agent_answer() -> None:
    out = await ReflectionNode(max_reflections=2).execute(
        {"current_agent": MAIN_AGENT_ID, "refusal_reason": "forbidden_intent:policy_prohibited", "output": UNSAFE}
    )
    assert out["next_step"] == "refusal"
    assert out["reflection_count"] == 0


def test_legacy_pack_reflection_node_still_retries_a_specialist(tmp_path: Path) -> None:
    turn = {
        "user": "Fix my note.",
        "explicit_agent": "writing-coach",
        "fake": {"agents": {"writing-coach": [UNSAFE, "Here is your note, fixed."]}},
    }
    trace = _run(_pack(tmp_path), [turn], LegacyReflectionNode).turns[0].trace
    assert trace.error is None and trace.answer == "Here is your note, fixed."


@pytest.mark.asyncio
async def test_reflection_node_still_retries_a_specialist_answer() -> None:
    out = await ReflectionNode(max_reflections=2).execute(
        {"current_agent": "writing-coach", "refusal_reason": "forbidden_intent:policy_prohibited", "output": UNSAFE}
    )
    assert out["next_step"] == "agent"
    assert out["reflection_count"] == 1
