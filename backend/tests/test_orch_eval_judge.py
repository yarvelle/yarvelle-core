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

"""Unit tests for the orch-eval LLM judge (no paid calls)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from yarvelle_core.testing.orch_eval.calibration import (
    CalibrationCase,
    cohen_kappa,
    load_calibration_dir,
    measure_agreement,
    verdict_matches,
)
from yarvelle_core.testing.orch_eval.defaults import (
    DEFAULT_OLLAMA_JUDGE_MODEL,
    DEFAULT_OLLAMA_SUBJECT_MODEL,
    DEFAULT_PROVIDER_JUDGE_MODEL,
    DEFAULT_PROVIDER_SUBJECT_MODEL,
)
from yarvelle_core.testing.orch_eval.judge import (
    MIN_AGREEMENT_FOR_GATE,
    SameModelJudgeError,
    aggregate_samples,
    assert_distinct_models,
    can_enable_gate,
    load_rubric,
    parse_failure_fallback,
    parse_judge_json,
    score_turn,
    strip_think_and_fences,
)


def test_paid_judge_differs_from_subject():
    assert DEFAULT_PROVIDER_SUBJECT_MODEL == "gpt-4o-mini"
    assert DEFAULT_PROVIDER_JUDGE_MODEL == "gpt-5-mini"
    assert DEFAULT_PROVIDER_JUDGE_MODEL != DEFAULT_PROVIDER_SUBJECT_MODEL
    assert DEFAULT_OLLAMA_JUDGE_MODEL == "llama3.1:8b"
    assert DEFAULT_OLLAMA_JUDGE_MODEL != DEFAULT_OLLAMA_SUBJECT_MODEL


def test_assert_distinct_models_refuses_match():
    with pytest.raises(SameModelJudgeError, match="must differ"):
        assert_distinct_models("gpt-4o-mini", "gpt-4o-mini")
    assert_distinct_models("gpt-4o-mini", "gpt-5-mini")
    assert_distinct_models("a", "a", allow_self_judge=True)


def test_strip_think_and_fences():
    raw = '<think>secret</think>\n```json\n{"score": 5, "verdict": "pass"}\n```\n'
    cleaned = strip_think_and_fences(raw)
    assert "secret" not in cleaned
    assert '"score": 5' in cleaned


def test_parse_judge_json_and_fallback():
    ok = parse_judge_json(
        'Here you go:\n{"score": 4, "verdict": "pass", "reasons": ["clear"], '
        '"evidence_quotes": ["You have $310"]}'
    )
    assert ok is not None and ok.score == 4 and ok.verdict == "pass" and ok.parse_ok
    assert parse_judge_json("not json") is None
    fb = parse_failure_fallback(raw="x", detail="boom")
    assert fb.score == 1 and fb.verdict == "fail" and not fb.parse_ok


def test_aggregate_majority_median_unsure():
    from yarvelle_core.testing.orch_eval.judge import JudgeVerdict

    samples = [
        JudgeVerdict(5, "pass"),
        JudgeVerdict(4, "pass"),
        JudgeVerdict(5, "pass"),
    ]
    agg = aggregate_samples(samples, rubric="synthesis", criteria="c", min_score=4)
    assert agg.score == 5 and agg.verdict == "pass" and not agg.unsure

    spread = [
        JudgeVerdict(5, "pass"),
        JudgeVerdict(2, "fail"),
        JudgeVerdict(3, "fail"),
    ]
    agg2 = aggregate_samples(spread, rubric="synthesis", criteria="c", min_score=4)
    assert agg2.unsure and agg2.verdict == "unsure"
    assert agg2.score == 3  # median


def test_load_bundled_rubrics():
    text = load_rubric("synthesis")
    assert "Score" in text or "score" in text.lower()
    for name in (
        "context_carryover",
        "followup",
        "failure_honesty",
        "delegation_fit",
    ):
        assert load_rubric(name)


class _ScriptedJudge(BaseChatModel):
    """Returns canned JSON replies in order (cycles the last)."""

    _replies: List[str] = PrivateAttr(default_factory=list)
    _i: int = PrivateAttr(default=0)

    def __init__(self, replies: List[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._replies = list(replies)
        self._i = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-judge"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self._replies:
            content = json.dumps(
                {"score": 1, "verdict": "fail", "reasons": ["empty"], "evidence_quotes": []}
            )
        else:
            content = self._replies[min(self._i, len(self._replies) - 1)]
            self._i += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def test_score_turn_with_scripted_model():
    reply = json.dumps(
        {
            "score": 5,
            "verdict": "pass",
            "reasons": ["good"],
            "evidence_quotes": ["310"],
        }
    )
    model = _ScriptedJudge([reply, reply, reply])
    result = score_turn(
        model,
        rubric="synthesis",
        criteria="clear budget synthesis",
        user="How much left?",
        answer="You have $310 left.",
        trace_summary={"agents": ["budget-planner"]},
        samples=3,
    )
    assert result.score == 5 and result.verdict == "pass"
    assert len(result.samples) == 3


def test_calibration_fixtures_are_human_labels():
    root = Path(__file__).resolve().parents[1] / "evals" / "orchestration" / "calibration"
    cases = load_calibration_dir(root)
    assert len(cases) >= 8
    assert all(c.kind == "human_label" for c in cases)
    assert all(isinstance(c, CalibrationCase) for c in cases)


def test_measure_agreement_with_scripted_perfect_judge():
    root = Path(__file__).resolve().parents[1] / "evals" / "orchestration" / "calibration"
    cases = load_calibration_dir(root)

    def reply_for(case: CalibrationCase) -> str:
        return json.dumps(
            {
                "score": case.label.score,
                "verdict": case.label.verdict,
                "reasons": ["label mirror"],
                "evidence_quotes": [],
            }
        )

    # One reply per sample per case — scripted judge advances each invoke.
    replies: List[str] = []
    for case in cases:
        r = reply_for(case)
        replies.extend([r, r, r])
    model = _ScriptedJudge(replies)
    report = measure_agreement(
        cases, model, judge_model="scripted", backend="fake", samples=3
    )
    assert report.agreement == pytest.approx(1.0)
    assert report.meets_gate_threshold
    assert can_enable_gate(report.agreement)
    assert not can_enable_gate(0.79)
    assert MIN_AGREEMENT_FOR_GATE == 0.8


def test_cohen_kappa_and_verdict_matches():
    assert cohen_kappa(["pass", "fail"], ["pass", "fail"]) == pytest.approx(1.0)
    assert verdict_matches("pass", "pass", unsure=False)
    assert not verdict_matches("pass", "fail", unsure=False)
    assert not verdict_matches("pass", "pass", unsure=True)


def test_gpt5_mini_in_cost_tables():
    from yarvelle_core.testing.orch_eval.cost import load_cost_tables

    tables = load_cost_tables()
    assert "gpt-5-mini" in tables
    assert tables["gpt-5-mini"].input_per_mtok == pytest.approx(0.25)
    assert tables["gpt-5-mini"].output_per_mtok == pytest.approx(2.00)
