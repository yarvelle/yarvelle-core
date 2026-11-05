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

"""Unit tests for eval pack loading and linting scenarios against a pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS
from yarvelle_core.testing.orch_eval.lint import lint_against_pack
from yarvelle_core.testing.orch_eval.loader import load_scenario_files, parse_scenario
from yarvelle_core.testing.orch_eval.pack import EvalPackError, find_pack_dir, load_eval_pack

BACKEND_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BACKEND_DIR / "evals" / "orchestration"


def _write(root: Path, agents: Dict[str, Dict[str, Any]], orchestration: Dict[str, Any], **extra: Any) -> Path:
    for agent_id, fields in agents.items():
        d = root / "agents" / agent_id
        d.mkdir(parents=True)
        data = {"id": agent_id, "title": agent_id.title(), "description": "x", "persona": "persona.md", "tools": [], "skills": [], **fields}
        (d / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        (d / "persona.md").write_text(f"You are the {agent_id} agent.\n", encoding="utf-8")
    (root / "pack.yaml").write_text(yaml.safe_dump({"schema": 1, "id": "p", "orchestration": orchestration, **extra}), encoding="utf-8")
    return root


SPEC = {
    "default_agent": "alpha",
    "fixed_routes": [{"route_id": "rush", "when": {"kind": "guardrail_flag", "flag": "rush"}, "agent_id": "alpha"}],
}


@pytest.fixture()
def pack(tmp_path: Path):
    return load_eval_pack(_write(tmp_path / "pk", {"alpha": {}, "beta": {}, "ghost": {"hidden": True}}, SPEC))


def test_pack_loads_agents_titles_and_routes(pack):
    assert pack.id == "p"
    assert pack.agent_ids == ["alpha", "beta", "ghost"]
    assert pack.hidden_ids == ["ghost"] and pack.visible_ids == ["alpha", "beta"]
    assert pack.route_ids == ["rush"] and pack.route_flags == ["rush"]
    assert pack.title("beta") == "Beta"


def test_pack_rejects_unknown_default_agent(tmp_path: Path):
    root = _write(tmp_path / "pk", {"alpha": {}}, {"default_agent": "nobody"})
    with pytest.raises(EvalPackError, match="unknown agent"):
        load_eval_pack(root)


def test_pack_rejects_bad_files(tmp_path: Path):
    with pytest.raises(EvalPackError):
        load_eval_pack(tmp_path)
    (tmp_path / "pack.yaml").write_text("schema: 1\nid: p\nsurprise: 1\n", encoding="utf-8")
    with pytest.raises(EvalPackError):
        load_eval_pack(tmp_path)


def test_offline_tools_are_local_and_validated(tmp_path: Path):
    root = _write(tmp_path / "ok", {"alpha": {}}, {"default_agent": "alpha"}, offline_tools={"alpha": ["lookup_notes"]})
    pack = load_eval_pack(root)
    spec = pack.registry.get_subagent("alpha", resolve_tools=True)
    names = [getattr(t, "name", None) for t in spec.get("tools", [])]
    assert "lookup_notes" in names
    bad = _write(tmp_path / "bad", {"alpha": {}}, {"default_agent": "alpha"}, offline_tools={"zeta": ["lookup_notes"]})
    with pytest.raises(EvalPackError, match="offline_tools"):
        load_eval_pack(bad)


def test_find_pack_dir_walks_up_by_id(tmp_path: Path):
    _write(tmp_path / "pack", {"alpha": {}}, {"default_agent": "alpha"})
    nested = tmp_path / "scenarios" / "deep"
    nested.mkdir(parents=True)
    (nested / "s.yaml").write_text("x: 1\n", encoding="utf-8")
    assert find_pack_dir(nested / "s.yaml", "p") == tmp_path / "pack"
    assert find_pack_dir(nested / "s.yaml", "missing") is None


def _scenario(turns, pack_id="p"):
    return parse_scenario({"schema": 1, "id": "s", "title": "t", "pack": pack_id, "backends": ["fake"], "turns": turns})


def test_lint_clean_scenario(pack):
    sc = _scenario([
        {"user": "x", "expect": {"route": "fixed_route:rush", "agents_exactly": ["alpha"], "agents_forbidden": ["ghost"]}},
        {"user": "y", "explicit_agent": "beta", "expect": {"route": "user_selected"}},
    ])
    assert lint_against_pack(sc, pack) == []


@pytest.mark.parametrize(
    "turn,needle",
    [
        ({"user": "x", "expect": {"agents_all_of": ["nobody"]}}, "not in pack"),
        ({"user": "x", "expect": {"agents_exactly": ["ghost"]}}, "hidden"),
        ({"user": "x", "explicit_agent": "ghost"}, "hidden"),
        ({"user": "x", "expect": {"route": "fixed_route:nope"}}, "fixed route"),
        ({"user": "x", "expect": {"route": "default_agent:whatever"}}, "default_agent reason"),
        ({"user": "x", "expect": {"route": "user_selected"}}, "needs explicit_agent"),
        ({"user": "x", "expect": {"provenance": {"must_cite": ["ghost"]}}}, "hidden"),
        ({"user": "x", "expect": {"notices": [{"code": "truncated", "agent_ids": ["nobody"]}]}}, "not in pack"),
        ({"user": "x", "fake": {"main": [{"task": ["nobody"]}]}}, "fake main task"),
        ({"user": "x", "fake": {"agents": {"ghost": ["hi"]}}}, "hidden"),
    ],
)
def test_lint_problems(pack, turn, needle):
    problems = lint_against_pack(_scenario([turn]), pack)
    assert problems and needle in problems[0], problems


def test_lint_allows_hidden_agent_as_fake_task_target(pack):
    sc = _scenario([{"user": "x", "expect": {"agents_forbidden": ["ghost"]}, "fake": {"main": [{"task": ["ghost"]}, {"answer": "no"}]}}])
    assert lint_against_pack(sc, pack) == []


def test_lint_wrong_pack(pack):
    assert "other" in lint_against_pack(_scenario([{"user": "x"}], pack_id="other"), pack)[0]


def test_shipped_scenarios_lint_against_shipped_pack(monkeypatch: pytest.MonkeyPatch):
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    pack = load_eval_pack(EVAL_DIR / "pack")
    loaded = load_scenario_files([EVAL_DIR / "scenarios"])
    assert 12 <= len(loaded) <= 15
    for path, sc in loaded:
        assert lint_against_pack(sc, pack) == [], path
    assert pack.hidden_ids == ["internal-auditor"]
    assert len(pack.agent_ids) in range(6, 9)
