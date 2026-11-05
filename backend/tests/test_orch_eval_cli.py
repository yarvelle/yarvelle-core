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

"""Unit tests for the orchestration eval command line."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yarvelle_core.cli import main as core_main
from yarvelle_core.testing.orch_eval.cli import main
from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS, EXIT_CI_REFUSED, EXIT_NOT_OPTED_IN

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = BACKEND_DIR / "evals" / "orchestration" / "scenarios"
PACK_DIR = BACKEND_DIR / "evals" / "orchestration" / "pack"


@pytest.fixture
def local_env(monkeypatch: pytest.MonkeyPatch):
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YARVELLE_EVAL", raising=False)
    return monkeypatch


def test_requires_opt_in(local_env, capsys):
    assert main(["lint", str(SCENARIOS_DIR)]) == EXIT_NOT_OPTED_IN
    assert "YARVELLE_EVAL=1" in capsys.readouterr().err


def test_help_works_locally_without_opt_in(local_env, capsys):
    assert main([]) == 0
    assert main(["--help"]) == 0
    assert "usage: yarvelle-core eval orchestration" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["--help"], ["lint", "x"], ["run", "x"]])
def test_refuses_everything_on_ci(local_env, capsys, argv):
    local_env.setenv("YARVELLE_EVAL", "1")
    local_env.setenv("GITHUB_ACTIONS", "true")
    assert main(argv) == EXIT_CI_REFUSED
    assert "never run on CI" in capsys.readouterr().err


def test_lint_valid(local_env, capsys):
    local_env.setenv("YARVELLE_EVAL", "1")
    assert main(["lint", str(SCENARIOS_DIR)]) == 0
    out = capsys.readouterr().out
    assert "smoke-single-turn" in out
    assert "valid" in out


def test_lint_invalid(local_env, capsys, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    (tmp_path / "bad.yaml").write_text("schema: 1\nid: x\n", encoding="utf-8")
    assert main(["lint", str(tmp_path)]) == 1
    assert "Scenario error" in capsys.readouterr().err


def test_lint_checks_agent_ids_against_pack(local_env, capsys, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    (tmp_path / "s.yaml").write_text(
        "schema: 1\nid: s\ntitle: t\npack: eval-neutral\nbackends: [fake]\n"
        "turns:\n  - user: hi\n    expect: {agents_exactly: [no-such-agent]}\n",
        encoding="utf-8",
    )
    assert main(["lint", "--pack", str(PACK_DIR), str(tmp_path)]) == 1
    assert "no-such-agent" in capsys.readouterr().err


def test_lint_reports_missing_pack(local_env, capsys, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    (tmp_path / "s.yaml").write_text(
        "schema: 1\nid: s\ntitle: t\npack: nowhere\nbackends: [fake]\nturns:\n  - user: hi\n",
        encoding="utf-8",
    )
    assert main(["lint", str(tmp_path)]) == 1
    assert "pass --pack" in capsys.readouterr().err


def test_run_requires_opt_in(local_env):
    assert main(["run", str(SCENARIOS_DIR)]) == EXIT_NOT_OPTED_IN


def test_run_fake_scenarios_pass_and_print_json(local_env, capsys, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    out_file = tmp_path / "result.json"
    assert main(["run", str(SCENARIOS_DIR), "--scenario", "smoke-single-turn", "--out", str(out_file)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(out_file.read_text(encoding="utf-8"))
    assert printed["passed"] is True
    assert printed["backend"]["backend"] == "fake"
    assert printed["totals"] == {"scenarios": 1, "passed": 1, "failed": 0}
    assert printed["scenarios"][0]["id"] == "smoke-single-turn"


def test_run_exits_1_on_broken_invariant(local_env, capsys, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    (tmp_path / "s.yaml").write_text(
        "schema: 1\nid: broken\ntitle: t\npack: eval-neutral\nbackends: [fake]\nturns:\n"
        "  - user: hi\n    expect: {agents_exactly: [writing-coach]}\n"
        "    fake: {main: [{answer: Hello there}]}\n",
        encoding="utf-8",
    )
    assert main(["run", "--pack", str(PACK_DIR), str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["passed"] is False
    assert "agents_exactly" in captured.err


def test_run_unknown_scenario_id(local_env, capsys):
    local_env.setenv("YARVELLE_EVAL", "1")
    assert main(["run", str(SCENARIOS_DIR), "--scenario", "nope"]) == 1
    assert "nope" in capsys.readouterr().err


def test_run_only_offers_free_fake_backend(local_env, capsys):
    local_env.setenv("YARVELLE_EVAL", "1")
    assert main(["run", "--backend", "provider", str(SCENARIOS_DIR)]) == 2


def test_lint_empty_dir(local_env, tmp_path: Path):
    local_env.setenv("YARVELLE_EVAL", "1")
    assert main(["lint", str(tmp_path)]) == 1


def test_core_cli_dispatches_eval_orchestration(local_env, capsys):
    local_env.setenv("YARVELLE_EVAL", "1")
    assert core_main(["eval", "orchestration", "lint", str(SCENARIOS_DIR)]) == 0
    local_env.setenv("CI", "true")
    assert core_main(["eval", "orchestration", "lint", str(SCENARIOS_DIR)]) == EXIT_CI_REFUSED


@pytest.mark.parametrize("argv", [["eval"], ["eval", "unknown"]])
def test_core_cli_rejects_unknown_eval_harness(local_env, capsys, argv):
    assert core_main(argv) == 2
    assert "orchestration" in capsys.readouterr().err


def test_import_does_not_load_provider_sdks():
    code = (
        "import sys, yarvelle_core.testing.orch_eval, yarvelle_core.testing.orch_eval.backends, "
        "yarvelle_core.testing.orch_eval.cli, yarvelle_core.testing.orch_eval.fake, "
        "yarvelle_core.testing.orch_eval.driver, yarvelle_core.testing.orch_eval.checks, "
        "yarvelle_core.testing.orch_eval.pack, yarvelle_core.testing.orch_eval.lint\n"
        "bad = [m for m in ('langchain_openai', 'langchain_anthropic', 'langchain_google_genai', "
        "'langchain_ollama', 'openai', 'anthropic') if m in sys.modules]\n"
        "print(','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in CI_ENV_VARS}
    env["PYTHONPATH"] = str(BACKEND_DIR / "src")
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
