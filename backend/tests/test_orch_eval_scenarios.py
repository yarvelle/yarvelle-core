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

"""Unit tests for the orchestration eval scenario schema and loader."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS
from yarvelle_core.testing.orch_eval.loader import (
    ScenarioLoadError,
    iter_scenario_files,
    load_scenario,
    load_scenarios,
    parse_scenario,
)
from yarvelle_core.testing.orch_eval.schema import SCHEMA_VERSION, Scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "evals" / "orchestration" / "scenarios"

BASE: dict[str, Any] = {
    "schema": 1,
    "id": "two-turn-example",
    "title": "Two turns",
    "tags": ["fanout"],
    "pack": "eval-neutral",
    "backends": ["fake", "ollama"],
    "samples": {"fake": 1},
    "turns": [
        {
            "user": "Plan a weekend and a budget.",
            "expect": {
                "route": "main_agent",
                "agents_all_of": ["trip-organizer", "budget-planner"],
                "agents_forbidden": ["writing-coach"],
                "max_task_calls": 2,
                "notices": [],
                "answer": {"must_mention": ["weekend", "/\\$\\s?600/"]},
                "provenance": {"must_cite": ["trip-organizer"]},
                "budget": {"latency_ms_p95": 20000, "tokens": 6000},
            },
            "judge": {"rubric": "synthesis", "criteria": "One ordered list.", "min_score": 4},
            "fake": {
                "main": [{"task": ["trip-organizer", "budget-planner"]}, {"answer": "Plan..."}],
                "agents": {"trip-organizer": ["Two nights."], "budget-planner": ["Split."]},
            },
        },
        {
            "user": "What about the second day?",
            "expect": {
                "same_agents_as_turn": {"turn": 1, "mode": "subset"},
                "task_states": {"trip-organizer": "completed"},
                "notices": [{"code": "agent_timed_out", "agent_ids": ["budget-planner"]}],
            },
        },
        {
            "user": "This is urgent.",
            "input": {"guardrail_flag": "urgent"},
            "expect": {
                "route": "fixed_route:urgent-escalation",
                "model_calls_before_route": 0,
                "agents_exactly": ["escalation-desk"],
            },
        },
    ],
}


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch: pytest.MonkeyPatch):
    """File loaders refuse on CI; these tests cover parsing, so clear CI markers."""
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _data(**overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    data.update(overrides)
    return data


def test_valid_scenario_parses():
    scenario = parse_scenario(_data())
    assert isinstance(scenario, Scenario)
    assert scenario.schema_version == SCHEMA_VERSION
    assert len(scenario.turns) == 3
    assert scenario.turns[2].expect.route == "fixed_route:urgent-escalation"
    assert scenario.turns[0].expect.answer.no_slug_leak is True


def test_samples_defaults():
    scenario = parse_scenario(_data())
    assert scenario.samples_for("fake") == 1
    assert scenario.samples_for("ollama") == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(unknown_key=1),
        lambda d: d["turns"][0].update(usr="typo"),
        lambda d: d["turns"][0]["expect"].update(agents_al_of=["x"]),
        lambda d: d["turns"][0]["expect"]["answer"].update(must_mentions=["x"]),
        lambda d: d["turns"][0]["fake"].update(extra=[]),
    ],
    ids=["top", "turn", "expect", "answer", "fake"],
)
def test_unknown_keys_fail(mutate):
    data = _data()
    mutate(data)
    with pytest.raises(ScenarioLoadError):
        parse_scenario(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema": 2},
        {"schema": None},
        {"id": "Bad Id"},
        {"backends": []},
        {"backends": ["fake", "fake"]},
        {"backends": ["remote"]},
        {"samples": {"provider": 3}},
        {"samples": {"fake": 0}},
        {"turns": []},
    ],
)
def test_invalid_top_level_fails(overrides):
    with pytest.raises(ScenarioLoadError):
        parse_scenario(_data(**overrides))


def test_missing_schema_version_fails():
    data = _data()
    del data["schema"]
    with pytest.raises(ScenarioLoadError, match="schema"):
        parse_scenario(data)


@pytest.mark.parametrize(
    "expect",
    [
        {"route": "somewhere"},
        {"route": "fixed_route:"},
        {"agents_all_of": ["a"], "agents_forbidden": ["a"]},
        {"agents_exactly": ["a"], "agents_forbidden": ["a"]},
        {"agents_any_of": ["a"], "agents_forbidden": ["a"]},
        {"agents_all_of": ["a", "a"]},
        {"agents_all_of": ["Not_Slug"]},
        {"min_task_calls": 3, "max_task_calls": 1},
        {"task_states": {"a": "lost"}},
        {"provenance": {"must_cite": ["a"], "must_not_cite": ["a"]}},
        {"budget": {"tokens": 0}},
    ],
)
def test_contradictory_or_invalid_expectations_fail(expect):
    data = _data()
    data["turns"][1]["expect"] = expect
    with pytest.raises(ScenarioLoadError):
        parse_scenario(data)


@pytest.mark.parametrize("ref", [2, 3])
def test_same_agents_as_turn_must_point_backwards(ref: int):
    data = _data()
    data["turns"][1]["expect"] = {"same_agents_as_turn": {"turn": ref}}
    with pytest.raises(ScenarioLoadError, match="earlier turn"):
        parse_scenario(data)


@pytest.mark.parametrize("step", [{}, {"task": ["a"], "answer": "x"}, {"task": []}])
def test_fake_step_needs_exactly_one_action(step):
    data = _data()
    data["turns"][0]["fake"]["main"] = [step]
    with pytest.raises(ScenarioLoadError):
        parse_scenario(data)


def test_fake_script_needs_fake_backend():
    data = _data(backends=["ollama"], samples={})
    with pytest.raises(ScenarioLoadError, match="fake"):
        parse_scenario(data)


def test_judge_score_range():
    data = _data()
    data["turns"][0]["judge"]["min_score"] = 6
    with pytest.raises(ScenarioLoadError):
        parse_scenario(data)


def test_non_mapping_fails():
    with pytest.raises(ScenarioLoadError, match="mapping"):
        parse_scenario(["not", "a", "mapping"])


def test_error_names_the_file_and_field(tmp_path: Path):
    data = _data()
    data["turns"][0]["expect"]["route"] = "nowhere"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ScenarioLoadError) as exc:
        load_scenario(path)
    assert str(path) in str(exc.value)
    assert "turns.0.expect.route" in str(exc.value)


def test_load_scenario_from_file(tmp_path: Path):
    path = tmp_path / "ok.yaml"
    path.write_text(yaml.safe_dump(_data()), encoding="utf-8")
    assert load_scenario(path).id == "two-turn-example"


def test_invalid_yaml(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="invalid YAML"):
        load_scenario(path)


def test_missing_file(tmp_path: Path):
    with pytest.raises(ScenarioLoadError):
        load_scenario(tmp_path / "absent.yaml")
    with pytest.raises(ScenarioLoadError, match="no such file"):
        load_scenarios([tmp_path / "absent"])


def test_iter_scenario_files_sorts_and_filters(tmp_path: Path):
    (tmp_path / "b.yaml").write_text("x: 1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.yml").write_text("x: 1", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignore", encoding="utf-8")
    files = iter_scenario_files([tmp_path, tmp_path / "b.yaml"])
    assert files == sorted([tmp_path / "b.yaml", tmp_path / "sub" / "a.yml"])
    with pytest.raises(ScenarioLoadError, match="yaml"):
        iter_scenario_files([tmp_path / "notes.md"])


def test_duplicate_ids_fail(tmp_path: Path):
    for name in ("one.yaml", "two.yaml"):
        (tmp_path / name).write_text(yaml.safe_dump(_data()), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="duplicate scenario id"):
        load_scenarios([tmp_path])


def test_bundled_scenarios_are_valid():
    scenarios = load_scenarios([SCENARIOS_DIR])
    assert scenarios, "expected at least one bundled scenario"
    assert len({s.id for s in scenarios}) == len(scenarios)
