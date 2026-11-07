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

"""Eval packs can supply the graph nodes a pack uses in production (#31).

A pack that replaces a node (for example its refusal node) with
``GraphBuilder.with_node`` gets the same node under eval, so refusal wording
checked by a scenario matches what the pack's users see.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from langchain_core.messages import AIMessage

from yarvelle_core.engine.builder import OVERRIDABLE_NODES
from yarvelle_core.engine.safety_policy import SafetyVerdict
from yarvelle_core.testing.orch_eval.driver import ScenarioRunner
from yarvelle_core.testing.orch_eval.fake import FakeBackend
from yarvelle_core.testing.orch_eval.pack import EvalPack, EvalPackError, KeywordFlagPolicy, load_eval_pack
from yarvelle_core.workflows.nodes.base import BaseNode

from tests.test_orch_eval_driver import scenario, write_pack

PACK_REFUSAL = "This pack cannot help with that. Please contact the help desk."


class _RefusingPolicy(KeywordFlagPolicy):
    def check_input(self, text: Optional[str], ctx: Any = None) -> SafetyVerdict:
        if "forbidden" in (text or "").lower():
            return SafetyVerdict(refused=True, reason="forbidden_intent:policy_prohibited")
        return SafetyVerdict(refused=False)


class PackRefusalNode(BaseNode):
    """A pack's own refusal node with its own wording."""

    builds = 0

    def __init__(self) -> None:
        super().__init__(name="refusal")
        PackRefusalNode.builds += 1

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "messages": [AIMessage(content=PACK_REFUSAL)],
            "output": PACK_REFUSAL,
            "is_refusal": True,
            "refused": True,
            "tool_calls": [],
            "next_step": "done",
        }


def _copy(base: EvalPack, cls: type) -> EvalPack:
    return cls(**{f.name: getattr(base, f.name) for f in dataclasses.fields(base)})


@dataclasses.dataclass(frozen=True)
class _PackWithRefusal(EvalPack):
    def safety_policy(self) -> KeywordFlagPolicy:
        return _RefusingPolicy(self.flag_words)

    def graph_nodes(self) -> Dict[str, Any]:
        return {"refusal": PackRefusalNode()}


@dataclasses.dataclass(frozen=True)
class _PackWithBadNode(_PackWithRefusal):
    def graph_nodes(self) -> Dict[str, Any]:
        return {"refusall": PackRefusalNode()}


REFUSED = {
    "user": "Do the forbidden thing.",
    "expect": {"answer": {"must_mention": ["help desk"], "must_not_mention": ["Yarvelle Core"]}},
}


def test_default_eval_pack_has_no_node_overrides(tmp_path: Path) -> None:
    assert load_eval_pack(write_pack(tmp_path / "pack")).graph_nodes() == {}


def test_pack_refusal_node_is_used_under_eval(tmp_path: Path) -> None:
    pack = _copy(load_eval_pack(write_pack(tmp_path / "pack")), _PackWithRefusal)
    result = asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario([REFUSED])))
    trace = result.turns[0].trace
    assert "refusal" in trace.nodes
    assert trace.answer == PACK_REFUSAL
    assert result.passed, result.failures()


def test_overrides_are_rebuilt_on_restart(tmp_path: Path) -> None:
    pack = _copy(load_eval_pack(write_pack(tmp_path / "pack")), _PackWithRefusal)
    PackRefusalNode.builds = 0
    turns = [REFUSED, {**REFUSED, "restart_before": True}]
    result = asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario(turns)))
    assert result.passed, result.failures()
    assert [t.trace.answer for t in result.turns] == [PACK_REFUSAL, PACK_REFUSAL]
    assert PackRefusalNode.builds == 2


def test_unknown_node_name_is_rejected(tmp_path: Path) -> None:
    pack = _copy(load_eval_pack(write_pack(tmp_path / "pack")), _PackWithBadNode)
    with pytest.raises(EvalPackError, match="refusall"):
        asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario([REFUSED])))


def test_overridable_nodes_cover_the_safety_nodes() -> None:
    for name in ("input_guardrail", "output_guardrail", "reflection", "refusal", "main_agent", "agent"):
        assert name in OVERRIDABLE_NODES
