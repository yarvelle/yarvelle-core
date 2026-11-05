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

"""Validates every orchestration scenario file against its eval pack (local-only, opt-in)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.lint import lint_against_pack
from yarvelle_core.testing.orch_eval.loader import iter_scenario_files, load_scenario
from yarvelle_core.testing.orch_eval.pack import EvalPackError, find_pack_dir, load_eval_pack

pytestmark = pytest.mark.orch_eval

HERE = Path(__file__).resolve().parent
SCENARIOS_DIR = HERE / "scenarios"
SCENARIO_FILES = iter_scenario_files([SCENARIOS_DIR])


@pytest.fixture(scope="module")
def packs() -> dict:
    loaded: dict = {}
    for path in SCENARIO_FILES:
        scenario = load_scenario(path)
        if scenario.pack in loaded:
            continue
        found = find_pack_dir(path, scenario.pack)
        if found is None:
            raise EvalPackError(f"{path}: pack {scenario.pack!r} not found next to the scenario")
        loaded[scenario.pack] = load_eval_pack(found)
    return loaded


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=[p.stem for p in SCENARIO_FILES])
def test_scenario_file_is_valid(path: Path, packs) -> None:
    scenario = load_scenario(path)
    assert scenario.turns
    pack = packs[scenario.pack]
    assert lint_against_pack(scenario, pack) == []
