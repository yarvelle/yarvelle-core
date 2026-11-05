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

"""Runs every scenario on the scripted fake backend (local-only, opt-in).

Each scenario goes through the real graph, one thread per scenario, and every
turn's checks must pass.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.driver import ScenarioRunner
from yarvelle_core.testing.orch_eval.fake import FakeBackend
from yarvelle_core.testing.orch_eval.loader import iter_scenario_files, load_scenario
from yarvelle_core.testing.orch_eval.pack import load_eval_pack

pytestmark = pytest.mark.orch_eval

HERE = Path(__file__).resolve().parent
SCENARIO_FILES = iter_scenario_files([HERE / "scenarios"])


@pytest.fixture(scope="module")
def pack():
    return load_eval_pack(HERE / "pack")


@pytest.mark.parametrize("path", SCENARIO_FILES, ids=[p.stem for p in SCENARIO_FILES])
def test_scenario_passes_on_fake_backend(path: Path, pack) -> None:
    scenario = load_scenario(path)
    if "fake" not in scenario.backends:
        pytest.skip("scenario does not list the fake backend")
    result = asyncio.run(ScenarioRunner(pack, FakeBackend()).run(scenario))
    assert result.passed, "\n".join(result.failures())
