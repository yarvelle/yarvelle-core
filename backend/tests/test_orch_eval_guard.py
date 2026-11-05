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

"""Unit tests for the orchestration eval run gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.guard import (
    CI_ENV_VARS,
    EXIT_CI_REFUSED,
    EXIT_NOT_OPTED_IN,
    EvalRefusedError,
    default_output_root,
    detect_ci,
    ensure_not_ci,
    ensure_opted_in,
    is_opted_in,
)


def test_ci_vars_cover_common_runners():
    for name in ("CI", "GITHUB_ACTIONS", "RUNNER_NAME", "GITLAB_CI", "BUILDKITE", "JENKINS_URL"):
        assert name in CI_ENV_VARS


def test_detect_ci_returns_names_in_fixed_order():
    env = {"RUNNER_NAME": "r1", "CI": "true", "HOME": "/tmp"}
    assert detect_ci(env) == ["CI", "RUNNER_NAME"]
    assert detect_ci({}) == []


@pytest.mark.parametrize("value", ["true", "1", "false", "0", "yes"])
def test_any_non_empty_ci_value_counts(value: str):
    assert detect_ci({"CI": value}) == ["CI"]


def test_empty_ci_value_does_not_count():
    assert detect_ci({"CI": ""}) == []


@pytest.mark.parametrize("value,expected", [("1", True), ("true", False), ("0", False), ("", False)])
def test_opt_in_needs_exactly_one(value: str, expected: bool):
    assert is_opted_in({"YARVELLE_EVAL": value}) is expected
    assert is_opted_in({}) is False


def test_ensure_not_ci_raises_exit_3_without_leaking_values():
    with pytest.raises(EvalRefusedError) as exc:
        ensure_not_ci({"GITHUB_ACTIONS": "secret-looking-value"})
    assert exc.value.exit_code == EXIT_CI_REFUSED == 3
    assert "GITHUB_ACTIONS" in str(exc.value)
    assert "secret-looking-value" not in str(exc.value)
    assert "no override" in str(exc.value)


def test_ci_refusal_wins_over_opt_in():
    with pytest.raises(EvalRefusedError) as exc:
        ensure_opted_in({"CI": "true", "YARVELLE_EVAL": "1"})
    assert exc.value.exit_code == EXIT_CI_REFUSED


def test_missing_opt_in_refuses_with_its_own_code():
    with pytest.raises(EvalRefusedError) as exc:
        ensure_opted_in({})
    assert exc.value.exit_code == EXIT_NOT_OPTED_IN
    assert "YARVELLE_EVAL=1" in str(exc.value)


def test_opted_in_locally_passes():
    ensure_opted_in({"YARVELLE_EVAL": "1"})


def test_ensure_not_ci_reads_process_env(monkeypatch: pytest.MonkeyPatch):
    for name in CI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    ensure_not_ci()
    monkeypatch.setenv("BUILDKITE", "true")
    with pytest.raises(EvalRefusedError):
        ensure_not_ci()


def test_default_output_root_is_under_home():
    root = default_output_root()
    assert root == Path.home() / ".yarvelle-evals"
    repo_root = Path(__file__).resolve().parent.parent.parent
    assert repo_root not in root.parents
