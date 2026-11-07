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

"""The eval driver starts every turn fresh, as the chat service does.

Regression for #30: the driver sent only the new message, so a turn after a
refusal re-read the previous turn's refusal from the checkpoint and failed.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any, List, Optional

from yarvelle_core.engine.safety_policy import SafetyVerdict
from yarvelle_core.testing.orch_eval.driver import ScenarioRunner
from yarvelle_core.testing.orch_eval.fake import FakeBackend
from yarvelle_core.testing.orch_eval.pack import EvalPack, KeywordFlagPolicy, load_eval_pack
from yarvelle_core.workflows.state import TURN_RESET_DEFAULTS, turn_reset_values

from tests.test_orch_eval_driver import scenario, write_pack


CHECKED_OUTPUTS: List[str] = []


class _RefusingPolicy(KeywordFlagPolicy):
    """Refuses inputs that say "forbidden" and answers that repeat a refusal."""

    def check_input(self, text: Optional[str], ctx: Any = None) -> SafetyVerdict:
        if "forbidden" in (text or "").lower():
            return SafetyVerdict(refused=True, reason="forbidden_intent:policy_prohibited")
        return SafetyVerdict(refused=False)

    def check_output(self, text: Optional[str], ctx: Any = None) -> SafetyVerdict:
        CHECKED_OUTPUTS.append(text or "")
        if "cannot make authoritative determinations" in (text or ""):
            return SafetyVerdict(refused=True, reason="forbidden_intent:policy_prohibited")
        return SafetyVerdict(refused=False)


@dataclasses.dataclass(frozen=True)
class _RefusingPack(EvalPack):
    def safety_policy(self) -> KeywordFlagPolicy:
        return _RefusingPolicy(self.flag_words)


def _pack(tmp_path: Path) -> EvalPack:
    base = load_eval_pack(write_pack(tmp_path / "pack"))
    return _RefusingPack(**{f.name: getattr(base, f.name) for f in dataclasses.fields(base)})


REFUSED = {"user": "Do the forbidden thing.", "expect": {"answer": {"must_not_mention": ["weekend"]}}}
ROUTINE = {
    "user": "Plan a weekend.",
    "expect": {"route": "main_agent", "agents_exactly": ["trip-organizer"], "answer": {"must_mention": ["weekend"]}},
    "fake": {"main": [{"task": ["trip-organizer"]}, {"answer": "Weekend plan ready."}], "agents": {"trip-organizer": ["Two nights."]}},
}


def test_routine_turn_after_a_refusal_runs_fresh(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    CHECKED_OUTPUTS.clear()
    result = asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario([REFUSED, ROUTINE])))
    first, second = (t.trace for t in result.turns)
    assert "refusal" in first.nodes
    assert second.error is None, second.error
    assert "refusal" not in second.nodes and "reflection" not in second.nodes
    assert second.answer == "Weekend plan ready."
    # The output guardrail checked this turn's answer, not the stale refusal.
    assert CHECKED_OUTPUTS and all("authoritative" not in t for t in CHECKED_OUTPUTS)
    assert result.passed, result.failures()


def test_refusal_after_a_routine_turn_still_refuses(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    result = asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario([ROUTINE, REFUSED])))
    first, second = (t.trace for t in result.turns)
    assert first.answer == "Weekend plan ready."
    assert "refusal" in second.nodes and second.error is None


def test_turn_reset_values_are_fresh_copies() -> None:
    a, b = turn_reset_values(), turn_reset_values()
    assert a == TURN_RESET_DEFAULTS
    assert a["refused"] is False and a["output"] == "" and a["reflection_count"] == 0
    a["tool_calls"].append("x")
    assert b["tool_calls"] == [] and TURN_RESET_DEFAULTS["tool_calls"] == []


def test_service_initial_input_uses_the_shared_reset() -> None:
    import inspect

    from yarvelle_core.engine import service

    assert "turn_reset_values()" in inspect.getsource(service)
