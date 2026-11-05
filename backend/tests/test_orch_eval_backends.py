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

"""Unit tests for the orchestration eval backend interface."""

from __future__ import annotations

from typing import Any

import pytest

from yarvelle_core.testing.orch_eval.backends import (
    BACKEND_NAMES,
    FREE,
    FREE_BACKENDS,
    CostTable,
    EvalBackend,
    Role,
    parse_role,
)


def test_backend_names():
    assert BACKEND_NAMES == ("fake", "replay", "ollama", "provider")
    assert "provider" not in FREE_BACKENDS
    assert FREE_BACKENDS <= set(BACKEND_NAMES)


def test_cost_table_math():
    table = CostTable(input_per_mtok=2.5, output_per_mtok=10.0)
    assert table.cost_usd(1_000_000, 0) == pytest.approx(2.5)
    assert table.cost_usd(200_000, 100_000) == pytest.approx(1.5)
    assert not table.is_free
    assert FREE.is_free
    assert FREE.cost_usd(123_456, 654_321) == 0


def test_cost_table_rejects_negatives():
    with pytest.raises(ValueError):
        CostTable(input_per_mtok=-1)
    with pytest.raises(ValueError):
        FREE.cost_usd(-1, 0)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("main", Role(kind="main")),
        ("judge", Role(kind="judge")),
        ("agent:trip-organizer", Role(kind="agent", agent_id="trip-organizer")),
    ],
)
def test_parse_role(value: str, expected: Role):
    role = parse_role(value)
    assert role == expected
    assert str(role) == value


@pytest.mark.parametrize("value", ["", "agent:", "agent:Bad Id", "subagent", "agent:a:b"])
def test_parse_role_rejects(value: str):
    with pytest.raises(ValueError):
        parse_role(value)


class _StubBackend:
    name = "fake"
    cost_per_mtok = FREE

    def model_for(self, role: Role) -> Any:
        return f"model-for-{role}"

    def describe(self) -> dict[str, Any]:
        return {"provider": "fake", "model": "scripted"}


def test_protocol_is_structural():
    backend = _StubBackend()
    assert isinstance(backend, EvalBackend)
    assert not isinstance(object(), EvalBackend)
    assert backend.model_for(parse_role("agent:a")) == "model-for-agent:a"
