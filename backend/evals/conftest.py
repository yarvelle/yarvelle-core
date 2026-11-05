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

"""Pytest gate for the local-only orchestration evals.

Everything under ``backend/evals`` is outside ``testpaths``, so the normal
suite never collects it. When it is collected explicitly:

* any CI environment variable stops the whole session with exit code 3,
  even with the opt-in set; there is no override;
* every item must carry the ``orch_eval`` marker;
* items are skipped unless ``YARVELLE_EVAL=1`` is set and the run selects
  the marker with ``-m orch_eval``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.guard import (
    EXIT_CI_REFUSED,
    OPT_IN_ENV_VAR,
    ci_refusal_message,
    detect_ci,
    is_opted_in,
)

EVALS_ROOT = Path(__file__).resolve().parent
MARKER = "orch_eval"


def _refuse_on_ci() -> None:
    detected = detect_ci()
    if detected:
        pytest.exit(ci_refusal_message(detected), returncode=EXIT_CI_REFUSED)


def _is_under_evals(path: Path) -> bool:
    try:
        path.resolve().relative_to(EVALS_ROOT)
    except ValueError:
        return False
    return True


def pytest_collect_file(file_path: Path, parent: pytest.Collector):
    """Refuses on CI before any eval module is imported."""
    if _is_under_evals(file_path):
        _refuse_on_ci()
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    _refuse_on_ci()
    marker_selected = MARKER in (config.getoption("markexpr", default="") or "")
    run = is_opted_in() and marker_selected
    skip = pytest.mark.skip(
        reason=(
            f"local-only orchestration eval: set {OPT_IN_ENV_VAR}=1 "
            f"and select it with -m {MARKER}"
        )
    )
    for item in items:
        if not _is_under_evals(Path(str(item.path))):
            continue
        if item.get_closest_marker(MARKER) is None:
            raise pytest.UsageError(
                f"{item.nodeid}: every item under backend/evals must be marked @pytest.mark.{MARKER}"
            )
        if not run:
            item.add_marker(skip)
