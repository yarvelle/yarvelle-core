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

"""Unit tests for ToolSpec and ToolSpecRegistry."""

from __future__ import annotations

import pytest

from yarvelle_core.engine.tool_registry import (
    DataFlows,
    ToolSpec,
    ToolSpecRegistry,
    _make_core_builtin_specs,
)


def test_toolspec_immutability_and_defaults():
    spec = ToolSpec(name="test_tool", description="Test description")
    assert spec.name == "test_tool"
    assert spec.risk_tier == "read"
    assert spec.trust == "trusted"
    assert isinstance(spec.data_flows, DataFlows)
    with pytest.raises(Exception):
        spec.name = "mutated"  # frozen


def test_toolspec_registry_registration_and_filtering():
    registry = ToolSpecRegistry()
    t1 = ToolSpec(name="core_tool", scopes={"core.main"})
    t2 = ToolSpec(name="finance_tool", scopes={"finance.accounts"})

    registry.register(t1, pack_id="core")
    registry.register(t2, pack_id="finance")

    assert registry.get("core_tool") == t1
    assert registry.get("finance_tool") == t2
    assert registry.get_pack_id("finance_tool") == "finance"

    # Filter for enabled packs
    tools_core = registry.list_for_enabled_packs([])
    assert t1 in tools_core
    assert t2 not in tools_core

    tools_finance = registry.list_for_enabled_packs(["finance"])
    assert t1 in tools_finance
    assert t2 in tools_finance


def test_core_builtin_specs_contains_18_tools():
    """Verify core defines exactly the 18 generic tool specs."""
    specs = _make_core_builtin_specs()
    assert len(specs) == 18
    names = {s.name for s in specs}
    assert "attach-read" in names
    assert "workspace-note" in names
    assert "skill-docs" in names or "skill_docs" in names
    assert "create_reminder" in names
    assert "list_reminders" in names
