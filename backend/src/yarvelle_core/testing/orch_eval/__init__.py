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

"""Local-only evaluation harness for multi-agent, multi-turn orchestration.

The harness drives scripted conversations through the orchestration runtime
and checks routing, delegation, failure handling and the final reply. It is
built to run on a developer machine only:

* scenarios live outside the normal test tree, so plain ``pytest`` never
  collects them;
* every run needs the explicit ``YARVELLE_EVAL=1`` opt-in;
* every entry point refuses to start, with exit code 3, when a CI
  environment variable is present, and there is no override;
* a guard test in the regular suite fails if a workflow ever references
  the harness.

Importing this package never touches the network, a model provider or a key.
"""

from __future__ import annotations

from yarvelle_core.testing.orch_eval.guard import (
    CI_ENV_VARS,
    EXIT_CI_REFUSED,
    EXIT_NOT_OPTED_IN,
    OPT_IN_ENV_VAR,
    EvalRefusedError,
    default_output_root,
    detect_ci,
    ensure_not_ci,
    ensure_opted_in,
    is_opted_in,
)
from yarvelle_core.testing.orch_eval.loader import (
    ScenarioLoadError,
    load_scenario,
    load_scenarios,
    parse_scenario,
)
from yarvelle_core.testing.orch_eval.schema import SCHEMA_VERSION, Scenario

__all__ = [
    "CI_ENV_VARS",
    "EXIT_CI_REFUSED",
    "EXIT_NOT_OPTED_IN",
    "OPT_IN_ENV_VAR",
    "SCHEMA_VERSION",
    "EvalRefusedError",
    "Scenario",
    "ScenarioLoadError",
    "default_output_root",
    "detect_ci",
    "ensure_not_ci",
    "ensure_opted_in",
    "is_opted_in",
    "load_scenario",
    "load_scenarios",
    "parse_scenario",
]
