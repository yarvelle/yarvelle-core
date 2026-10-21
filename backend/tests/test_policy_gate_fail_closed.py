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

"""Policy gate must fail closed and honour the canonical under-13 age band."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yarvelle_core.engine.tool_exec import ToolContext, evaluate_policy_gate
from yarvelle_core.engine.tool_registry import ToolSpec, ToolSpecRegistry
from yarvelle_core.schemas.age_band import CHILD_UNDER_13, canonical_age_band, is_child_under_13


def _ctx(autonomy: str = "A2", **extra) -> ToolContext:
    return ToolContext(user_id="u-1", profile_id="p-1", autonomy=autonomy, extra=extra)


@pytest.mark.parametrize("tier", ["banana", "", "READ_ONLY", None])
def test_unknown_or_empty_tier_requires_approval(tier) -> None:
    spec = SimpleNamespace(name="weird", risk_tier=tier)
    decision = evaluate_policy_gate(_ctx(), spec, {})
    assert decision.decision == "needs_approval"
    assert "fail-closed" in decision.reason


def test_spec_without_tier_attribute_requires_approval() -> None:
    decision = evaluate_policy_gate(_ctx(), SimpleNamespace(name="no-tier"), {})
    assert decision.decision == "needs_approval"


def test_declared_read_tier_still_allowed() -> None:
    decision = evaluate_policy_gate(_ctx(), ToolSpec(name="lookup", risk_tier="read"), {})
    assert decision.decision == "allow"


def test_tier_is_normalised_before_matching() -> None:
    decision = evaluate_policy_gate(_ctx(autonomy="A1"), SimpleNamespace(name="x", risk_tier=" Write_Local "), {})
    assert decision.decision == "allow"


@pytest.mark.parametrize("band", ["child_under_13", "child_u13", "CHILD-U13", "child", "under_13"])
def test_under_13_aliases_block_external_writes(band) -> None:
    spec = ToolSpec(name="send", risk_tier="write_external")
    decision = evaluate_policy_gate(_ctx(), spec, {}, consents={"external_write_consent": True}, age_band=band)
    assert decision.decision == "blocked"


def test_under_13_band_from_context_extra() -> None:
    spec = ToolSpec(name="send", risk_tier="write_external")
    decision = evaluate_policy_gate(_ctx(age_band="child_u13"), spec, {})
    assert decision.decision == "blocked"


@pytest.mark.parametrize("band", ["child_u13", "child_under_13"])
def test_registry_hides_external_writes_for_under_13_aliases(band) -> None:
    registry = ToolSpecRegistry()
    registry.register(ToolSpec(name="read_it", risk_tier="read"))
    registry.register(ToolSpec(name="send_it", risk_tier="write_external"))
    names = {spec.name for spec in registry.list_for_profile("p-1", age_band=band)}
    assert names == {"read_it"}


def test_canonical_age_band_mapping() -> None:
    assert canonical_age_band(None) == "adult"
    assert canonical_age_band("  ") == "adult"
    assert canonical_age_band("child_u13") == CHILD_UNDER_13
    assert canonical_age_band("teen") == "teen_13_17"
    assert canonical_age_band("older_adult") == "older_adult"
    assert canonical_age_band("martian") == "martian"
    assert is_child_under_13("Child_U13")
    assert not is_child_under_13("teen_13_17")
