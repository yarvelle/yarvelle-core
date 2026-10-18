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

"""Unit tests for PackSpec, validation rules, discovery, and routing hints."""

from __future__ import annotations

import pytest

from yarvelle_core.pack.loader import discover_and_load_packs
from yarvelle_core.pack.routing import collect_routing_hints, compose_orchestrator_routing_prompt
from yarvelle_core.pack.spec import (
    PackEvalsSpec,
    PackMigrationsSpec,
    PackProvidesSpec,
    PackSpec,
    ReadScopeSpec,
    ScopeDefinitionSpec,
)
from yarvelle_core.pack.validator import PackValidationError, validate_pack_spec


def test_valid_pack_spec():
    """Verify standard valid PackSpec validates with no errors."""
    spec = PackSpec(
        id="finance",
        name="Household Finance Pack",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0,<0.2.0",
        owned_scopes=["finance.accounts", "finance.transactions"],
        risk_tier_max="T1",
    )
    validate_pack_spec(spec, core_version="0.1.0")


def test_rule_1_scope_prefix_mismatch():
    """Rule 1: Owned scope must match pack domain prefix."""
    bad_spec = PackSpec(
        id="finance",
        name="Bad Finance",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["alpha.accounts"],
        risk_tier_max="T1",
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(bad_spec)
    assert "does not match pack domain" in str(exc.value)


def test_rule_2_unowned_tool_scopes():
    """Rule 2: Pack tools cannot specify scopes outside pack owned scopes."""
    from yarvelle_core.engine.tool_registry import ToolSpec

    bad_tool = ToolSpec(name="bad_tool", scopes={"foreign.scope"})
    spec = PackSpec(
        id="finance",
        name="Bad Tool Scope",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["finance.accounts"],
        risk_tier_max="T1",
        tools=[bad_tool],
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(spec)
    assert "is not in pack owned_scopes" in str(exc.value)


def test_rule_3_declared_reads_collision():
    """Rule 3: Declared reads cannot overlap with owned scopes."""
    spec = PackSpec(
        id="finance",
        name="Read Collision",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["finance.accounts"],
        declared_reads=["finance.accounts"],
        risk_tier_max="T1",
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(spec)
    assert "collides with owned scopes" in str(exc.value)


def test_rule_4_t2_pack_requires_evals():
    """Rule 4: Tier 2 or Tier 3 packs must provide evals specification."""
    spec = PackSpec(
        id="finance",
        name="T2 No Evals",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["finance.accounts"],
        risk_tier_max="T2",
        evals=None,
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(spec)
    assert "evals specification" in str(exc.value)


def test_rule_5_unprefixed_tables():
    """Rule 5: Non-allowlisted tables must carry pack_ prefix."""
    class BadModel:
        __tablename__ = "unprefixed_accounts"

    spec = PackSpec(
        id="finance",
        name="Bad Tables",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["finance.accounts"],
        risk_tier_max="T1",
        scoped_models=[BadModel],
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(spec)
    assert "does not start with" in str(exc.value)


def test_rule_6_semver_core_mismatch():
    """Rule 6: Core version must satisfy requires_core specification."""
    spec = PackSpec(
        id="finance",
        name="Future Core",
        version="0.1.0",
        domain="finance",
        requires_core=">=2.0.0",
        owned_scopes=["finance.accounts"],
        risk_tier_max="T1",
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack_spec(spec, core_version="0.1.0")
    assert "is incompatible with pack requires_core" in str(exc.value)


def test_routing_hints_and_orchestrator_prompt():
    """Verify routing hints collection and dynamic prompt synthesis."""
    from yarvelle_core.schemas.routing import RoutingHints

    hints_obj = RoutingHints(
        domain="finance",
        description="Manages checking, savings, and investments",
        default_agent="finance-guide",
        domains_info={"categories": "accounts, investments"},
    )
    spec = PackSpec(
        id="finance",
        name="Finance Pack",
        version="0.1.0",
        domain="finance",
        requires_core=">=0.1.0",
        owned_scopes=["finance.accounts"],
        risk_tier_max="T1",
        routing_hints=hints_obj,
    )
    hints = collect_routing_hints([spec])
    assert len(hints) == 1
    assert hints[0].domain == "finance"
    assert hints[0].description == "Manages checking, savings, and investments"

    prompt = compose_orchestrator_routing_prompt(hints, product_name="Yarvelle Test")
    assert "Yarvelle Test" in prompt
    assert "finance" in prompt
    assert "accounts" in prompt


def test_discover_and_load_packs_graceful():
    """Verify entry points discovery runs cleanly when no external packs installed."""
    loaded = discover_and_load_packs()
    assert hasattr(loaded, "packs")
    assert isinstance(loaded.packs, dict)
