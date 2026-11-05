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


@pytest.mark.parametrize("argv", [[], ["--help"], ["lint", "x"]])
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
        "yarvelle_core.testing.orch_eval.cli\n"
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
