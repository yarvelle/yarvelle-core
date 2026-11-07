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

"""Pack-level delegation instructions for the main agent (``orchestration.delegation``).

The base main-agent prompt tells the model to answer directly when no specialist
is needed. A pack can add guidance on when to hand work to its specialists
instead, for example on follow-up questions. These tests pin the schema, the
prompt layout, and that the router passes the setting through.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from yarvelle_core.engine.orchestration.runtime import (
    MAIN_AGENT_PROMPT,
    HybridRouter,
    compose_main_prompt,
)
from yarvelle_core.schemas.orchestration import DelegationSpec, PackOrchestrationSpec, SynthesisSpec

DELEGATION_HEADING = "When to hand work to specialists:"
SYNTHESIS_HEADING = "How to compose the reply:"
HINT = "Send follow-up questions about an earlier specialist answer back to that specialist."


def test_delegation_spec_defaults_to_empty_and_is_optional() -> None:
    spec = PackOrchestrationSpec(default_agent="budget-planner")
    assert spec.delegation.instructions == ""


def test_delegation_spec_is_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        PackOrchestrationSpec.model_validate({"default_agent": "budget-planner", "delegation": {"rules": "x"}})
    with pytest.raises(ValidationError):
        DelegationSpec(instructions="x" * 4001)


def test_delegation_spec_parses_from_pack_yaml_shape() -> None:
    spec = PackOrchestrationSpec.model_validate(
        {"default_agent": "budget-planner", "delegation": {"instructions": HINT}}
    )
    assert spec.delegation.instructions == HINT


def test_prompt_without_delegation_is_unchanged() -> None:
    assert compose_main_prompt() == MAIN_AGENT_PROMPT
    assert compose_main_prompt(None, None, DelegationSpec(instructions="  \n ")) == MAIN_AGENT_PROMPT
    assert DELEGATION_HEADING not in compose_main_prompt(None, SynthesisSpec(instructions="Be brief."))


def test_prompt_renders_delegation_under_its_own_heading() -> None:
    prompt = compose_main_prompt(None, None, DelegationSpec(instructions=f"  {HINT}  "))
    assert prompt.startswith(MAIN_AGENT_PROMPT)
    assert prompt == f"{MAIN_AGENT_PROMPT}\n\n{DELEGATION_HEADING}\n{HINT}"


def test_delegation_comes_before_synthesis() -> None:
    prompt = compose_main_prompt(
        "Custom base.", SynthesisSpec(instructions="Be brief."), DelegationSpec(instructions=HINT)
    )
    assert prompt == f"Custom base.\n\n{DELEGATION_HEADING}\n{HINT}\n\n{SYNTHESIS_HEADING}\nBe brief."


def test_runtime_system_prompt_includes_pack_delegation() -> None:
    spec = PackOrchestrationSpec(
        default_agent="budget-planner",
        delegation=DelegationSpec(instructions=HINT),
        synthesis=SynthesisSpec(instructions="Be brief."),
    )
    runtime = HybridRouter(registry=None, model=None, spec=spec)
    assert f"{DELEGATION_HEADING}\n{HINT}" in runtime.system_prompt
    assert runtime.system_prompt.index(DELEGATION_HEADING) < runtime.system_prompt.index(SYNTHESIS_HEADING)


def test_runtime_without_spec_keeps_base_prompt() -> None:
    runtime = HybridRouter(registry=None, model=None, spec=None)
    assert runtime.system_prompt == MAIN_AGENT_PROMPT


@pytest.mark.parametrize(
    "path",
    [
        Path(__file__).resolve().parents[2] / "schemas" / "pack.schema.json",
        Path(__file__).resolve().parents[1] / "src" / "yarvelle_core" / "schemas" / "pack.schema.json",
    ],
)
def test_committed_pack_schema_includes_delegation(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    orch = schema["$defs"]["PackOrchestrationSpec"]["properties"]
    assert orch["delegation"]["$ref"] == "#/$defs/DelegationSpec"
    assert schema["$defs"]["DelegationSpec"]["additionalProperties"] is False
