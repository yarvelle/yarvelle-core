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

"""Spend ceiling and token cost metering for orchestration eval runs.

Free backends (fake, replay, ollama) never spend money. The paid ``provider``
backend refuses to start unless ``--max-usd`` is given and greater than zero.
A live meter tracks tokens and estimated dollars and stops the run before the
cap would be exceeded. Pricing comes from the local ``cost.yaml`` next to this
module; nothing is fetched from the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional

import yaml

from yarvelle_core.testing.orch_eval.backends import FREE, CostTable

DEFAULT_COST_FILE = Path(__file__).with_name("cost.yaml")


class SpendRefusedError(RuntimeError):
    """Raised when a paid run is refused or the spend cap is hit."""


def load_cost_tables(path: Optional[Path] = None) -> Dict[str, CostTable]:
    """Loads ``model -> CostTable`` from a YAML file.

    Expected shape::

        models:
          gpt-4o-mini:
            input_per_mtok: 0.15
            output_per_mtok: 0.60
    """
    target = path or DEFAULT_COST_FILE
    if not target.is_file():
        return {}
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    models = raw.get("models") or {}
    out: Dict[str, CostTable] = {}
    for name, entry in models.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"cost.yaml models.{name} must be a mapping")
        out[str(name)] = CostTable(
            input_per_mtok=float(entry.get("input_per_mtok", 0) or 0),
            output_per_mtok=float(entry.get("output_per_mtok", 0) or 0),
        )
    return out


def cost_table_for(model: str, tables: Optional[Mapping[str, CostTable]] = None) -> CostTable:
    """Looks up a model price; unknown models are treated as free (and reported)."""
    tables = tables if tables is not None else load_cost_tables()
    if model in tables:
        return tables[model]
    # Longest prefix match: "gpt-4o-mini-2024-07-18" -> "gpt-4o-mini", not "gpt-4o".
    matches = [(key, table) for key, table in tables.items() if model.startswith(key)]
    if matches:
        key, table = max(matches, key=lambda item: len(item[0]))
        return table
    return FREE


@dataclass
class SpendMeter:
    """Running token and dollar totals for one eval run."""

    max_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    model_calls: int = 0
    stopped: bool = False
    stop_reason: Optional[str] = None
    by_model: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_usd < 0:
            raise ValueError("max_usd cannot be negative")

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.usd)

    def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        table: CostTable,
    ) -> float:
        """Adds one model call. Returns the dollars added. Raises if over cap."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        if self.stopped:
            raise SpendRefusedError(self.stop_reason or "spend cap already reached")
        added = table.cost_usd(input_tokens, output_tokens)
        if self.max_usd > 0 and self.usd + added > self.max_usd + 1e-12:
            self.stopped = True
            self.stop_reason = (
                f"spend cap of ${self.max_usd:.4f} would be exceeded "
                f"(spent ${self.usd:.4f}, next call ~${added:.4f})"
            )
            raise SpendRefusedError(self.stop_reason)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.usd += added
        self.model_calls += 1
        bucket = self.by_model.setdefault(model, {"input_tokens": 0, "output_tokens": 0, "usd": 0.0, "calls": 0})
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["usd"] += added
        bucket["calls"] += 1
        return added

    def would_exceed(self, estimated_usd: float) -> bool:
        return self.max_usd > 0 and self.usd + estimated_usd > self.max_usd + 1e-12

    def snapshot(self) -> Dict[str, Any]:
        return {
            "max_usd": self.max_usd,
            "usd": round(self.usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_calls": self.model_calls,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "by_model": {
                k: {
                    "input_tokens": int(v["input_tokens"]),
                    "output_tokens": int(v["output_tokens"]),
                    "usd": round(float(v["usd"]), 6),
                    "calls": int(v["calls"]),
                }
                for k, v in self.by_model.items()
            },
        }


def require_paid_budget(max_usd: Optional[float], *, backend: str) -> float:
    """Returns the spend cap for a paid backend, or refuses clearly.

    Default and missing values are treated as $0 and refuse the run. Free
    backends ignore the cap and return 0.
    """
    from yarvelle_core.testing.orch_eval.backends import FREE_BACKENDS

    if backend in FREE_BACKENDS:
        return 0.0
    if max_usd is None or max_usd <= 0:
        raise SpendRefusedError(
            f"backend {backend!r} can spend money; pass --max-usd with a value "
            f"greater than 0 (default is $0 and refuses to run). Approve the "
            f"spend before each paid run."
        )
    return float(max_usd)


def estimate_run_usd(
    *,
    scenarios: int,
    turns_per_scenario: float,
    samples: int,
    model_calls_per_turn: float,
    input_tokens_per_call: int,
    output_tokens_per_call: int,
    table: CostTable,
    judge_calls_per_turn: float = 0.0,
    judge_table: Optional[CostTable] = None,
) -> Dict[str, Any]:
    """Rough offline estimate used by ``--estimate``. No network."""
    sut_calls = scenarios * turns_per_scenario * samples * model_calls_per_turn
    judge_calls = scenarios * turns_per_scenario * samples * judge_calls_per_turn
    sut_in = int(sut_calls * input_tokens_per_call)
    sut_out = int(sut_calls * output_tokens_per_call)
    judge_in = int(judge_calls * input_tokens_per_call)
    judge_out = int(judge_calls * output_tokens_per_call)
    jtable = judge_table or FREE
    usd = table.cost_usd(sut_in, sut_out) + jtable.cost_usd(judge_in, judge_out)
    return {
        "scenarios": scenarios,
        "samples": samples,
        "sut_model_calls": int(sut_calls),
        "judge_model_calls": int(judge_calls),
        "input_tokens": sut_in + judge_in,
        "output_tokens": sut_out + judge_out,
        "usd": round(usd, 6),
    }


__all__ = [
    "DEFAULT_COST_FILE",
    "SpendMeter",
    "SpendRefusedError",
    "cost_table_for",
    "estimate_run_usd",
    "load_cost_tables",
    "require_paid_budget",
]
