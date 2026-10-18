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

"""Scope Conformance Suite Test Runner."""

from __future__ import annotations

from pathlib import Path
import pytest

from yarvelle_core.conformance import (
    IsolationLayer,
    ScopeConformanceRunner,
    run_conformance_matrix,
)
from yarvelle_core.conformance.fixtures.synthetic_alpha import SyntheticAlphaPackFixture
from yarvelle_core.conformance.fixtures.synthetic_finance import SyntheticFinancePackFixture
from yarvelle_core.conformance.layers import (
    Layer01OrmTest,
    Layer02CasTest,
    Layer03Fts5Test,
    Layer04MemoryTest,
    Layer05VaultTest,
    Layer06ToolGateTest,
    Layer07PromptTest,
    Layer08ApiTest,
    Layer09ExportTest,
    Layer10AuditTest,
    Layer11RedactionTest,
)


@pytest.fixture
async def conformance_env(tmp_path: Path):
    """Sets up an isolated runner with in-memory SQLite, partitioned CAS root, and synthetic pack doubles."""
    runner = ScopeConformanceRunner(
        pack_a=SyntheticAlphaPackFixture(),
        pack_b=SyntheticFinancePackFixture(),
        work_dir=tmp_path / "conformance",
    )
    await runner.setup()
    try:
        yield runner
    finally:
        await runner.teardown()


@pytest.mark.asyncio
async def test_scope_conformance_full_11_layers_matrix(conformance_env: ScopeConformanceRunner):
    """Executes the full bidirectional 11-layer isolation matrix."""
    result = await conformance_env.run_full_matrix()
    assert result.passed is True, f"Conformance violations: {result.violations}"
    assert len(result.violations) == 0
    for layer in IsolationLayer:
        assert result.layer_results.get(layer) is True, f"Layer {layer.value} failed"


@pytest.mark.asyncio
async def test_public_run_conformance_matrix_api(tmp_path: Path):
    """Verifies public run_conformance_matrix entry point."""
    result = await run_conformance_matrix(
        pack_a=SyntheticAlphaPackFixture(),
        pack_b=SyntheticFinancePackFixture(),
        work_dir=tmp_path / "public_matrix",
    )
    assert result.passed is True
    assert len(result.violations) == 0


@pytest.mark.asyncio
async def test_conformance_layer_01_orm(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer01OrmTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_02_cas(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer02CasTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_03_fts5(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer03Fts5Test()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_04_memory(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer04MemoryTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_05_vault(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer05VaultTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_06_tool_gate(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer06ToolGateTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_07_prompt(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer07PromptTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_08_api(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer08ApiTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_09_export(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer09ExportTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_10_audit(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer10AuditTest()])
    assert res.passed is True, f"Violations: {res.violations}"


@pytest.mark.asyncio
async def test_conformance_layer_11_redaction(conformance_env: ScopeConformanceRunner):
    res = await conformance_env.run_pair(conformance_env.pack_a, conformance_env.pack_b, [Layer11RedactionTest()])
    assert res.passed is True, f"Violations: {res.violations}"
