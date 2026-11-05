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

"""Validates every orchestration scenario file (local-only, opt-in)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.loader import iter_scenario_files, load_scenario

pytestmark = pytest.mark.orch_eval

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
SCENARIO_FILES = iter_scenario_files([SCENARIOS_DIR])


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=[p.stem for p in SCENARIO_FILES])
def test_scenario_file_is_valid(path: Path) -> None:
    scenario = load_scenario(path)
    assert scenario.turns
