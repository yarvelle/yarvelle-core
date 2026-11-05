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

"""Unit tests for the orchestration eval spend guard (fakes only, $0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.testing.orch_eval.backends import CostTable
from yarvelle_core.testing.orch_eval.cost import (
    SpendMeter,
    SpendRefusedError,
    cost_table_for,
    estimate_run_usd,
    load_cost_tables,
    require_paid_budget,
)
from yarvelle_core.testing.orch_eval.provider_backend import ProviderBackend


def test_require_paid_budget_free_backends():
    assert require_paid_budget(None, backend="fake") == 0.0
    assert require_paid_budget(0, backend="ollama") == 0.0


def test_require_paid_budget_refuses_default_zero():
    with pytest.raises(SpendRefusedError, match="--max-usd"):
        require_paid_budget(0, backend="provider")
    with pytest.raises(SpendRefusedError, match="--max-usd"):
        require_paid_budget(None, backend="provider")
    with pytest.raises(SpendRefusedError, match="--max-usd"):
        require_paid_budget(-1, backend="provider")


def test_require_paid_budget_accepts_positive():
    assert require_paid_budget(1.25, backend="provider") == 1.25


def test_spend_meter_tracks_and_stops(tmp_path: Path):
    table = CostTable(input_per_mtok=1_000_000.0, output_per_mtok=0.0)  # $1 per input token
    meter = SpendMeter(max_usd=1.5)
    assert meter.record(model="x", input_tokens=1, output_tokens=0, table=table) == pytest.approx(1.0)
    with pytest.raises(SpendRefusedError, match="would be exceeded"):
        meter.record(model="x", input_tokens=1, output_tokens=0, table=table)
    assert meter.stopped
    snap = meter.snapshot()
    assert snap["usd"] == pytest.approx(1.0)
    assert snap["model_calls"] == 1


def test_load_bundled_cost_tables():
    tables = load_cost_tables()
    assert "gpt-4o-mini" in tables
    assert tables["gpt-4o-mini"].input_per_mtok == pytest.approx(0.15)
    assert cost_table_for("gpt-4o-mini-2024-07-18", tables).output_per_mtok == pytest.approx(0.60)
    assert cost_table_for("unknown-local-model", tables).is_free


def test_estimate_run_usd_math():
    table = CostTable(input_per_mtok=1.0, output_per_mtok=2.0)
    out = estimate_run_usd(
        scenarios=2,
        turns_per_scenario=2,
        samples=3,
        model_calls_per_turn=1,
        input_tokens_per_call=1_000_000,
        output_tokens_per_call=500_000,
        table=table,
    )
    # 2*2*3*1 = 12 calls; 12M in * $1 + 6M out * $2 = 12 + 12 = 24
    assert out["sut_model_calls"] == 12
    assert out["usd"] == pytest.approx(24.0)


def test_provider_backend_refuses_without_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SpendRefusedError, match="--max-usd"):
        ProviderBackend(max_usd=0, load_key=False)


def test_provider_backend_refuses_without_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SpendRefusedError, match="no API key"):
        ProviderBackend(max_usd=1.0, load_key=True)


def test_provider_backend_describe_hides_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key_file = tmp_path / "key"
    key_file.write_text("sk-test-not-real\n", encoding="utf-8")
    backend = ProviderBackend(max_usd=0.5, key_file=str(key_file), load_key=True)
    described = backend.describe()
    blob = str(described)
    assert "sk-test-not-real" not in blob
    assert described["key_loaded"] is True
    assert described["max_usd"] == 0.5
