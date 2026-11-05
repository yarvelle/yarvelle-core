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

"""Write orchestration eval run reports and compute aggregates.

Reports land under ``~/.yarvelle-evals/<run_id>/`` by default (outside the
repo). Each run directory gets ``results.json``, ``report.md`` and a
self-contained ``report.html``. Nothing is written into the working tree.
"""

from __future__ import annotations

import html
import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

DEFAULT_OUT_ROOT = Path.home() / ".yarvelle-evals"

# Built-in invariant check names (must stay green on every turn).
HARD_RULE_NAMES = frozenset(
    {
        "turn_completed",
        "answer_present",
        "task_call_cap",
        "hidden_agents_not_run",
        "known_agents_only",
        "provenance_titles",
        "no_subagent_tokens",
        "route_audited",
        "turn_tasks_recorded",
        "fake_script",
        "hidden_pick_refused",
        "model_calls_before_route",
    }
)


def default_out_root() -> Path:
    override = os.environ.get("YARVELLE_EVALS_DIR")
    return Path(override).expanduser() if override else DEFAULT_OUT_ROOT


def new_run_id(backend: str, when: Optional[datetime] = None) -> str:
    """Stable, sortable run id: ``YYYYMMDDTHHMMSS-<backend>`` in UTC."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in backend) or "run"
    return f"{stamp}-{safe}"


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, math.ceil(pct / 100.0 * len(ordered))) - 1
    return ordered[min(rank, len(ordered) - 1)]


def _scenario_score(scenario: Mapping[str, Any]) -> float:
    return 100.0 if scenario.get("passed") else 0.0


def _iter_turns(document: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for scenario in document.get("scenarios") or []:
        for turn in scenario.get("turns") or []:
            yield turn


def _hard_failures(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for scenario in document.get("scenarios") or []:
        sid = scenario.get("id")
        sample = scenario.get("sample")
        if scenario.get("error"):
            out.append(
                {
                    "scenario": sid,
                    "sample": sample,
                    "turn": None,
                    "check": "scenario_error",
                    "detail": scenario.get("error"),
                }
            )
        for turn in scenario.get("turns") or []:
            for check in turn.get("checks") or []:
                if check.get("status") != "fail":
                    continue
                name = str(check.get("name") or "")
                if name in HARD_RULE_NAMES or name.startswith("invariant"):
                    out.append(
                        {
                            "scenario": sid,
                            "sample": sample,
                            "turn": turn.get("turn"),
                            "check": name,
                            "detail": check.get("detail") or "",
                        }
                    )
    return out


def _scores_by_scenario(document: Mapping[str, Any]) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = {}
    for scenario in document.get("scenarios") or []:
        sid = str(scenario.get("id") or "")
        buckets.setdefault(sid, []).append(_scenario_score(scenario))
    return {sid: (sum(vals) / len(vals) if vals else 0.0) for sid, vals in buckets.items()}


def _route_summary(document: Mapping[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for turn in _iter_turns(document):
        trace = turn.get("trace") or {}
        route = str(trace.get("route") or "unknown")
        key = route.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _task_summary(document: Mapping[str, Any]) -> Dict[str, Any]:
    started = 0
    by_state: Dict[str, int] = {}
    agents: Dict[str, int] = {}
    for turn in _iter_turns(document):
        trace = turn.get("trace") or {}
        for task in trace.get("tasks") or []:
            started += 1
            state = str(task.get("final_state") or "unknown")
            by_state[state] = by_state.get(state, 0) + 1
            agent = str(task.get("agent_id") or "?")
            agents[agent] = agents.get(agent, 0) + 1
    return {
        "started": started,
        "by_state": dict(sorted(by_state.items())),
        "by_agent": dict(sorted(agents.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def compute_aggregates(document: Mapping[str, Any]) -> Dict[str, Any]:
    """Derives suite-level numbers used by reports and baseline compare."""
    scenarios = list(document.get("scenarios") or [])
    latencies = [
        float((turn.get("trace") or {}).get("latency_ms") or 0.0)
        for turn in _iter_turns(document)
    ]
    scores = _scores_by_scenario(document)
    suite_score = (sum(scores.values()) / len(scores)) if scores else 0.0
    hard = _hard_failures(document)
    spend = document.get("spend") or {}
    cost_usd = float(spend.get("usd") or 0.0)
    return {
        "scenarios": len({s.get("id") for s in scenarios}),
        "scenario_rows": len(scenarios),
        "passed_rows": sum(1 for s in scenarios if s.get("passed")),
        "failed_rows": sum(1 for s in scenarios if not s.get("passed")),
        "suite_score": round(suite_score, 4),
        "scenario_scores": {k: round(v, 4) for k, v in sorted(scores.items())},
        "hard_rule_failures": hard,
        "hard_rule_failure_count": len(hard),
        "latency_ms": {
            "count": len(latencies),
            "p50": (None if (p50 := _percentile(latencies, 50)) is None else round(p50, 3)),
            "p95": (None if (p95 := _percentile(latencies, 95)) is None else round(p95, 3)),
            "max": (None if not latencies else round(max(latencies), 3)),
            "mean": (None if not latencies else round(statistics.fmean(latencies), 3)),
        },
        "cost_usd": cost_usd,
        "routes": _route_summary(document),
        "tasks": _task_summary(document),
    }


def enrich_document(
    document: MutableMapping[str, Any],
    *,
    run_id: str,
    out_dir: Path,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Adds run metadata and aggregates. Mutates and returns ``document``."""
    document["run_id"] = run_id
    document["out_dir"] = str(out_dir)
    document["started_at"] = started_at or document.get("started_at")
    document["finished_at"] = finished_at or datetime.now(timezone.utc).isoformat()
    document["aggregates"] = compute_aggregates(document)
    return dict(document)


def render_markdown(document: Mapping[str, Any]) -> str:
    agg = document.get("aggregates") or compute_aggregates(document)
    totals = document.get("totals") or {}
    backend = document.get("backend") or {}
    lines: List[str] = []
    lines.append(f"# Orchestration eval report — `{document.get('run_id', '')}`")
    lines.append("")
    passed = totals.get("passed", agg.get("passed_rows"))
    scenarios = totals.get("scenarios", agg.get("scenario_rows"))
    hard_n = agg.get("hard_rule_failure_count", 0)
    suite = float(agg.get("suite_score") or 0.0)
    lat = agg.get("latency_ms") or {}
    cost = float(agg.get("cost_usd") or 0.0)
    status = "PASS" if document.get("passed") and hard_n == 0 else "FAIL"
    lines.append(
        f"**{status}** — {passed}/{scenarios} scenario rows · "
        f"suite score {suite:.1f} · hard-rule failures {hard_n} · "
        f"p95 latency {lat.get('p95')} ms · cost ${cost:.4f}"
    )
    lines.append("")
    lines.append("## Run")
    lines.append("")
    lines.append(f"- Backend: `{backend.get('backend', backend)}`")
    if backend.get("subject_model"):
        lines.append(f"- Subject model: `{backend.get('subject_model')}`")
    if backend.get("judge_model"):
        lines.append(f"- Judge model: `{backend.get('judge_model')}`")
    lines.append(f"- Started: {document.get('started_at')}")
    lines.append(f"- Finished: {document.get('finished_at')}")
    lines.append(f"- Output: `{document.get('out_dir')}`")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Scenario rows | {scenarios} |")
    lines.append(f"| Passed | {passed} |")
    lines.append(f"| Failed | {totals.get('failed', agg.get('failed_rows'))} |")
    lines.append(f"| Suite score | {suite:.2f} |")
    lines.append(f"| Hard-rule failures | {hard_n} |")
    lines.append(f"| Latency p50 / p95 (ms) | {lat.get('p50')} / {lat.get('p95')} |")
    lines.append(f"| Cost (USD) | {cost:.6f} |")
    lines.append("")
    routes = agg.get("routes") or {}
    if routes:
        lines.append("## Routes")
        lines.append("")
        for name, count in routes.items():
            lines.append(f"- `{name}`: {count}")
        lines.append("")
    tasks = agg.get("tasks") or {}
    if tasks.get("started"):
        lines.append("## Tasks")
        lines.append("")
        lines.append(f"- Started: {tasks.get('started')}")
        by_state = tasks.get("by_state") or {}
        if by_state:
            lines.append("- By state: " + ", ".join(f"`{k}`={v}" for k, v in by_state.items()))
        lines.append("")
    hard = agg.get("hard_rule_failures") or []
    if hard:
        lines.append("## Hard-rule failures")
        lines.append("")
        for item in hard:
            lines.append(
                f"- `{item.get('scenario')}` turn {item.get('turn')}: "
                f"**{item.get('check')}** — {item.get('detail')}"
            )
        lines.append("")
    failed = [s for s in (document.get("scenarios") or []) if not s.get("passed")]
    if failed:
        lines.append("## Failures")
        lines.append("")
        for s in failed:
            sample = f" sample {s.get('sample')}" if s.get("sample") is not None else ""
            lines.append(f"### `{s.get('id')}`{sample}")
            for f in s.get("failures") or []:
                lines.append(f"- {f}")
            lines.append("")
    lines.append("## Per-scenario")
    lines.append("")
    lines.append("| Scenario | Sample | Passed | Turns | Failures |")
    lines.append("| --- | --- | --- | --- | --- |")
    for s in document.get("scenarios") or []:
        fails = "; ".join(s.get("failures") or []) or "—"
        sample = s.get("sample") if s.get("sample") is not None else "—"
        lines.append(
            f"| `{s.get('id')}` | {sample} | "
            f"{'yes' if s.get('passed') else 'no'} | {len(s.get('turns') or [])} | {fails} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_html(document: Mapping[str, Any]) -> str:
    agg = document.get("aggregates") or compute_aggregates(document)
    totals = document.get("totals") or {}
    backend = document.get("backend") or {}
    status = "PASS" if document.get("passed") and agg.get("hard_rule_failure_count", 0) == 0 else "FAIL"
    esc = html.escape

    def row(*cells: Any) -> str:
        return "<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in cells) + "</tr>"

    scenario_rows = []
    for s in document.get("scenarios") or []:
        scenario_rows.append(
            row(
                s.get("id"),
                s.get("sample") if s.get("sample") is not None else "—",
                "yes" if s.get("passed") else "no",
                len(s.get("turns") or []),
                "; ".join(s.get("failures") or []) or "—",
            )
        )

    timelines = []
    for s in document.get("scenarios") or []:
        turns_html = []
        for turn in s.get("turns") or []:
            trace = turn.get("trace") or {}
            tasks = trace.get("tasks") or []
            task_bits = ", ".join(
                f"{esc(str(t.get('agent_id')))}:{esc(str(t.get('final_state')))}" for t in tasks
            ) or "—"
            notices = ", ".join(esc(str(n.get("code"))) for n in (trace.get("notices") or [])) or "—"
            answer = esc((trace.get("answer") or "")[:240])
            turns_html.append(
                "<li>"
                f"<strong>turn {esc(str(turn.get('turn')))}</strong> "
                f"route=<code>{esc(str(trace.get('route')))}</code> "
                f"agents=<code>{esc(','.join(str(a) for a in (trace.get('agents') or [])))}</code> "
                f"tasks=[{task_bits}] notices=[{notices}] "
                f"latency={esc(str(trace.get('latency_ms')))} ms "
                f"<div class='answer'>{answer}</div>"
                "</li>"
            )
        sample = f" sample {esc(str(s.get('sample')))}" if s.get("sample") is not None else ""
        timelines.append(
            f"<section><h3>{esc(str(s.get('id')))}{sample}"
            f" — {'pass' if s.get('passed') else 'FAIL'}</h3>"
            f"<ol>{''.join(turns_html)}</ol></section>"
        )

    lat = agg.get("latency_ms") or {}
    cost = float(agg.get("cost_usd") or 0.0)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Orchestration eval {esc(str(document.get('run_id')))}</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #111; }}
h1,h2,h3 {{ margin-top: 1.4rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.2rem; }}
th,td {{ border: 1px solid #ccc; padding: 0.35rem 0.55rem; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.status-PASS {{ color: #0a7a2f; font-weight: 700; }}
.status-FAIL {{ color: #b00020; font-weight: 700; }}
.answer {{ color: #444; font-size: 0.9rem; margin-top: 0.25rem; white-space: pre-wrap; }}
code {{ background: #f6f6f6; padding: 0 0.25rem; }}
</style></head><body>
<h1>Orchestration eval report</h1>
<p class="status-{esc(status)}">{esc(status)} — {esc(str(totals.get('passed')))}/{esc(str(totals.get('scenarios')))} scenario rows ·
suite {esc(str(agg.get('suite_score')))} · hard-rule failures {esc(str(agg.get('hard_rule_failure_count')))} ·
p95 {esc(str(lat.get('p95')))} ms · cost ${esc(f'{cost:.4f}')}</p>
<h2>Run</h2>
<ul>
<li>Run id: <code>{esc(str(document.get('run_id')))}</code></li>
<li>Backend: <code>{esc(str(backend.get('backend', backend)))}</code></li>
<li>Output: <code>{esc(str(document.get('out_dir')))}</code></li>
<li>Started: {esc(str(document.get('started_at')))}</li>
<li>Finished: {esc(str(document.get('finished_at')))}</li>
</ul>
<h2>Per-scenario</h2>
<table><thead><tr><th>Scenario</th><th>Sample</th><th>Passed</th><th>Turns</th><th>Failures</th></tr></thead>
<tbody>{''.join(scenario_rows)}</tbody></table>
<h2>Timelines</h2>
{''.join(timelines) or '<p>No turns.</p>'}
</body></html>
"""


def write_run_reports(document: MutableMapping[str, Any], out_dir: Path) -> Path:
    """Writes results.json, report.md and report.html under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(document, indent=2, sort_keys=False, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(document) + "\n", encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(document), encoding="utf-8")
    return out_dir


__all__ = [
    "DEFAULT_OUT_ROOT",
    "HARD_RULE_NAMES",
    "compute_aggregates",
    "default_out_root",
    "enrich_document",
    "new_run_id",
    "render_html",
    "render_markdown",
    "write_run_reports",
]
