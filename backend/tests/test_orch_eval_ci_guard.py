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

"""CI guard for the local-only orchestration evals.

This test runs in the normal suite, on CI, on purpose: it fails the build if
a workflow ever starts running the evals, if the eval directory becomes part
of the default test paths, or if the CI refusal stops working.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

from yarvelle_core.testing.orch_eval.guard import CI_ENV_VARS, EXIT_CI_REFUSED, EvalRefusedError
from yarvelle_core.testing.orch_eval.loader import load_scenario, load_scenarios

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
EVALS_DIR = BACKEND_DIR / "evals"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
SMOKE_SCENARIO = EVALS_DIR / "orchestration" / "scenarios" / "smoke-single-turn.yaml"

FORBIDDEN_WORKFLOW_PATTERNS = [
    r"backend/evals",
    r"evals/orchestration",
    r"YARVELLE_EVAL",
    r"orch_eval",
    r"eval\s+orchestration",
    r"eval-orch",
    r"ollama",
    r"OPENAI_API_KEY",
    r"ANTHROPIC_API_KEY",
    r"GOOGLE_API_KEY",
    r"GEMINI_API_KEY",
]
_FORBIDDEN_RE = re.compile("|".join(FORBIDDEN_WORKFLOW_PATTERNS), re.IGNORECASE)


def find_forbidden_references(text: str) -> list[str]:
    """Returns the forbidden references found in a workflow file's text."""
    return sorted({m.group(0) for m in _FORBIDDEN_RE.finditer(text)})


def _workflow_files() -> list[Path]:
    return sorted(
        p for p in WORKFLOWS_DIR.glob("*") if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _env_without_ci(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CI_ENV_VARS}
    env["PYTHONPATH"] = str(BACKEND_DIR / "src")
    env.update(extra)
    return env


def test_workflows_exist():
    assert _workflow_files(), f"no workflow files found under {WORKFLOWS_DIR}"


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_no_workflow_references_the_evals(workflow: Path):
    hits = find_forbidden_references(workflow.read_text(encoding="utf-8"))
    assert not hits, (
        f"{workflow.relative_to(REPO_ROOT)} references local-only eval material {hits}. "
        "Orchestration evals must never run on CI."
    )


def test_scanner_flags_eval_references():
    sample = "run: YARVELLE_EVAL=1 pytest backend/evals -m orch_eval\nenv:\n  K: ${{ secrets.OPENAI_API_KEY }}\n"
    assert find_forbidden_references(sample) == [
        "OPENAI_API_KEY",
        "YARVELLE_EVAL",
        "backend/evals",
        "orch_eval",
    ]
    assert find_forbidden_references("run: pytest backend/tests/") == []


def test_evals_are_outside_default_test_paths():
    config = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_opts = config["tool"]["pytest"]["ini_options"]
    assert pytest_opts["testpaths"] == ["tests"]
    assert "orch_eval" in " ".join(pytest_opts.get("markers", []))
    assert EVALS_DIR.is_dir()
    assert (BACKEND_DIR / "tests") not in EVALS_DIR.parents
    assert not list((BACKEND_DIR / "tests").rglob("evals/orchestration"))


def test_evals_are_not_packaged():
    config = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    targets = config["tool"]["hatch"]["build"]["targets"]
    assert targets["wheel"]["packages"] == ["src/yarvelle_core"]
    assert not any("evals" in entry for entry in targets["sdist"]["include"])


def test_justfile_test_recipe_skips_the_evals():
    text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    test_recipe = re.search(r"^test:\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE)
    assert test_recipe is not None
    assert "evals" not in test_recipe.group(1)
    assert "YARVELLE_EVAL" not in test_recipe.group(1)


@pytest.mark.parametrize("ci_var", ["CI", "GITHUB_ACTIONS", "RUNNER_NAME"])
def test_loader_refuses_on_ci(monkeypatch: pytest.MonkeyPatch, ci_var: str):
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("YARVELLE_EVAL", "1")
    monkeypatch.setenv(ci_var, "true")
    with pytest.raises(EvalRefusedError) as exc:
        load_scenario(SMOKE_SCENARIO)
    assert exc.value.exit_code == EXIT_CI_REFUSED
    with pytest.raises(EvalRefusedError):
        load_scenarios([EVALS_DIR])


@pytest.mark.parametrize("ci_var", ["CI", "GITHUB_ACTIONS", "RUNNER_NAME"])
def test_cli_exits_3_on_ci_even_when_opted_in(ci_var: str):
    proc = subprocess.run(
        [sys.executable, "-m", "yarvelle_core.testing.orch_eval", "lint", str(EVALS_DIR)],
        env=_env_without_ci(**{ci_var: "true", "YARVELLE_EVAL": "1"}),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == EXIT_CI_REFUSED, proc.stdout + proc.stderr
    assert "never run on CI" in proc.stderr
    assert "ok " not in proc.stdout


def test_pytest_on_evals_exits_3_on_ci_even_when_opted_in():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(EVALS_DIR), "-m", "orch_eval", "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND_DIR,
        env=_env_without_ci(GITHUB_ACTIONS="true", YARVELLE_EVAL="1"),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == EXIT_CI_REFUSED, proc.stdout + proc.stderr
    assert "never run on CI" in proc.stdout + proc.stderr
