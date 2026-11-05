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

"""Baseline store and regression compare for orchestration eval runs.

A baseline is a saved ``results.json``. Comparing a new run against it flags:

* any hard-rule failure in the new run;
* a drop of 10 or more points on one scenario score;
* a drop of 5 or more points on the suite score;
* p95 latency up 25% or more (paid runs only by default, or when
  ``check_latency`` is set; fake/replay/ollama skip this);
* cost up 20% or more (when the baseline cost is > 0).

Regressions make the compare exit non-zero. Improvements are listed so a
better run can be accepted as the next baseline.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from yarvelle_core.testing.orch_eval.report import compute_aggregates, default_out_root

SCENARIO_DROP_POINTS = 10.0
SUITE_DROP_POINTS = 5.0
LATENCY_P95_RISE = 0.25
COST_RISE = 0.20

EXIT_REGRESSION = 2


@dataclass
class Thresholds:
    scenario_drop_points: float = SCENARIO_DROP_POINTS
    suite_drop_points: float = SUITE_DROP_POINTS
    latency_p95_rise: float = LATENCY_P95_RISE
    cost_rise: float = COST_RISE


@dataclass
class DiffItem:
    kind: str
    detail: str
    scenario: Optional[str] = None
    baseline: Optional[float] = None
    current: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompareResult:
    regressions: List[DiffItem] = field(default_factory=list)
    improvements: List[DiffItem] = field(default_factory=list)
    baseline_run_id: Optional[str] = None
    current_run_id: Optional[str] = None

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "current_run_id": self.current_run_id,
            "has_regression": self.has_regression,
            "regressions": [r.to_dict() for r in self.regressions],
            "improvements": [i.to_dict() for i in self.improvements],
        }


def load_results(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"results file is not an object: {path}")
    if "aggregates" not in data:
        data["aggregates"] = compute_aggregates(data)
    return data


def baselines_dir(root: Optional[Path] = None) -> Path:
    return (root or default_out_root()) / "baselines"


def baseline_key(backend: Mapping[str, Any]) -> str:
    name = str(backend.get("backend") or "unknown")
    model = str(backend.get("subject_model") or backend.get("model") or "default")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{name}-{model}").strip("-")
    return safe or "unknown-default"


def resolve_baseline_ref(ref: str, root: Optional[Path] = None) -> Path:
    """Resolves a path, run id, or ``latest:<backend>:<model>`` to results.json."""
    root = root or default_out_root()
    candidate = Path(ref).expanduser()
    if candidate.is_file():
        return candidate
    if candidate.is_dir() and (candidate / "results.json").is_file():
        return candidate / "results.json"
    run_dir = root / ref
    if run_dir.is_dir() and (run_dir / "results.json").is_file():
        return run_dir / "results.json"
    if ref.startswith("latest:"):
        parts = ref.split(":", 2)
        if len(parts) != 3:
            raise FileNotFoundError(
                "latest baseline ref must look like latest:<backend>:<model>"
            )
        key = baseline_key({"backend": parts[1], "subject_model": parts[2]})
        pointer = baselines_dir(root) / f"{key}.json"
        if not pointer.is_file():
            raise FileNotFoundError(f"no saved baseline for {key}")
        return pointer
    raise FileNotFoundError(f"baseline not found: {ref}")


def save_baseline(results_path: Path, root: Optional[Path] = None) -> Path:
    """Copies ``results.json`` into the baselines store keyed by backend+model."""
    root = root or default_out_root()
    data = load_results(results_path)
    key = baseline_key(data.get("backend") or {})
    dest_dir = baselines_dir(root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{key}.json"
    dest.write_text(json.dumps(data, indent=2, sort_keys=False, default=str) + "\n", encoding="utf-8")
    # Also record which run it came from.
    meta = dest_dir / f"{key}.meta.json"
    meta.write_text(
        json.dumps(
            {
                "key": key,
                "run_id": data.get("run_id"),
                "source": str(results_path),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dest


def compare_runs(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    thresholds: Optional[Thresholds] = None,
    *,
    check_latency: Optional[bool] = None,
) -> CompareResult:
    """Compares two enriched results documents.

    ``check_latency`` defaults to True only for the paid ``provider`` backend.
    Free backends (fake, replay, ollama) skip the p95 latency rule unless a
    caller passes ``check_latency=True``.
    """
    thr = thresholds or Thresholds()
    backend_name = str((current.get("backend") or {}).get("backend") or "")
    if check_latency is None:
        check_latency = backend_name == "provider"
    cur_agg = current.get("aggregates") or compute_aggregates(current)
    base_agg = baseline.get("aggregates") or compute_aggregates(baseline)
    result = CompareResult(
        baseline_run_id=baseline.get("run_id"),
        current_run_id=current.get("run_id"),
    )

    hard = cur_agg.get("hard_rule_failure_count") or 0
    if hard:
        result.regressions.append(
            DiffItem(
                kind="hard_rule",
                detail=f"{hard} hard-rule failure(s) in the current run",
                current=float(hard),
                baseline=float(base_agg.get("hard_rule_failure_count") or 0),
            )
        )

    cur_scores: Mapping[str, float] = cur_agg.get("scenario_scores") or {}
    base_scores: Mapping[str, float] = base_agg.get("scenario_scores") or {}
    for sid, base_score in base_scores.items():
        cur_score = cur_scores.get(sid)
        if cur_score is None:
            result.regressions.append(
                DiffItem(
                    kind="scenario_missing",
                    detail=f"scenario {sid} present in baseline but missing now",
                    scenario=sid,
                    baseline=base_score,
                )
            )
            continue
        drop = base_score - cur_score
        if drop >= thr.scenario_drop_points:
            result.regressions.append(
                DiffItem(
                    kind="scenario_score",
                    detail=f"scenario {sid} dropped {drop:.1f} points",
                    scenario=sid,
                    baseline=base_score,
                    current=cur_score,
                )
            )
        elif cur_score - base_score >= thr.scenario_drop_points:
            result.improvements.append(
                DiffItem(
                    kind="scenario_score",
                    detail=f"scenario {sid} rose {cur_score - base_score:.1f} points",
                    scenario=sid,
                    baseline=base_score,
                    current=cur_score,
                )
            )

    suite_drop = float(base_agg.get("suite_score") or 0.0) - float(cur_agg.get("suite_score") or 0.0)
    if suite_drop >= thr.suite_drop_points:
        result.regressions.append(
            DiffItem(
                kind="suite_score",
                detail=f"suite score dropped {suite_drop:.1f} points",
                baseline=float(base_agg.get("suite_score") or 0.0),
                current=float(cur_agg.get("suite_score") or 0.0),
            )
        )
    elif -suite_drop >= thr.suite_drop_points:
        result.improvements.append(
            DiffItem(
                kind="suite_score",
                detail=f"suite score rose {-suite_drop:.1f} points",
                baseline=float(base_agg.get("suite_score") or 0.0),
                current=float(cur_agg.get("suite_score") or 0.0),
            )
        )

    if check_latency:
        base_p95 = (base_agg.get("latency_ms") or {}).get("p95")
        cur_p95 = (cur_agg.get("latency_ms") or {}).get("p95")
        if base_p95 is not None and cur_p95 is not None and float(base_p95) > 0:
            rise = (float(cur_p95) - float(base_p95)) / float(base_p95)
            if rise >= thr.latency_p95_rise:
                result.regressions.append(
                    DiffItem(
                        kind="latency_p95",
                        detail=f"p95 latency rose {rise * 100:.1f}%",
                        baseline=float(base_p95),
                        current=float(cur_p95),
                    )
                )
            elif rise <= -thr.latency_p95_rise:
                result.improvements.append(
                    DiffItem(
                        kind="latency_p95",
                        detail=f"p95 latency fell {-rise * 100:.1f}%",
                        baseline=float(base_p95),
                        current=float(cur_p95),
                    )
                )

    base_cost = float(base_agg.get("cost_usd") or 0.0)
    cur_cost = float(cur_agg.get("cost_usd") or 0.0)
    if base_cost > 0:
        rise = (cur_cost - base_cost) / base_cost
        if rise >= thr.cost_rise:
            result.regressions.append(
                DiffItem(
                    kind="cost",
                    detail=f"cost rose {rise * 100:.1f}%",
                    baseline=base_cost,
                    current=cur_cost,
                )
            )
        elif rise <= -thr.cost_rise:
            result.improvements.append(
                DiffItem(
                    kind="cost",
                    detail=f"cost fell {-rise * 100:.1f}%",
                    baseline=base_cost,
                    current=cur_cost,
                )
            )

    return result


def render_compare_markdown(compare: CompareResult) -> str:
    lines = [
        f"# Baseline compare",
        "",
        f"- Baseline: `{compare.baseline_run_id}`",
        f"- Current: `{compare.current_run_id}`",
        f"- Regressions: {len(compare.regressions)}",
        f"- Improvements: {len(compare.improvements)}",
        "",
    ]
    if compare.regressions:
        lines.append("## Regressions")
        lines.append("")
        for item in compare.regressions:
            lines.append(f"- **{item.kind}**: {item.detail}")
        lines.append("")
    if compare.improvements:
        lines.append("## Improvements")
        lines.append("")
        for item in compare.improvements:
            lines.append(f"- **{item.kind}**: {item.detail}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "COST_RISE",
    "EXIT_REGRESSION",
    "LATENCY_P95_RISE",
    "SCENARIO_DROP_POINTS",
    "SUITE_DROP_POINTS",
    "CompareResult",
    "DiffItem",
    "Thresholds",
    "baseline_key",
    "baselines_dir",
    "compare_runs",
    "load_results",
    "render_compare_markdown",
    "resolve_baseline_ref",
    "save_baseline",
]
