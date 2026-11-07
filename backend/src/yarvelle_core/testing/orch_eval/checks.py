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

"""Deterministic checks of one turn against its expectations.

Every check is a pure function of a :class:`TurnTrace`, the turn's
expectations and the pack, so the same trace always gives the same verdict.
Each returns a :class:`CheckResult` that says what was expected and what was
seen. ``skip`` means the expectation was not set (or needs a later harness
step, such as the judge).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence

from yarvelle_core.testing.orch_eval.schema import NoticeExpectation, Turn, TurnExpectation
from yarvelle_core.testing.orch_eval.trace import TurnTrace

CheckStatus = Literal["pass", "fail", "skip"]

MAIN_AGENT_ID = "main-agent"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "fail"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PackView:
    """The pack facts the checks need: titles, hidden agents and the call cap."""

    titles: Mapping[str, str]
    hidden: frozenset
    max_agents: int

    @property
    def agent_ids(self) -> List[str]:
        return sorted(self.titles)


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, "pass", detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "fail", detail)


def _skip(name: str, detail: str = "not set") -> CheckResult:
    return CheckResult(name, "skip", detail)


def _set(values: Iterable[str]) -> List[str]:
    return sorted(set(values))


# ---------------------------------------------------------------- text helpers


def text_matches(pattern: str, text: str) -> bool:
    """Case-insensitive substring match, or a regex when written as ``/.../``."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], text, flags=re.IGNORECASE) is not None
    return pattern.lower() in text.lower()


def leaked_ids(answer: str, agent_ids: Iterable[str]) -> List[str]:
    """Agent ids that appear in ``answer`` as whole tokens."""
    out = []
    for agent_id in agent_ids:
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(agent_id)}(?![A-Za-z0-9_-])", answer):
            out.append(agent_id)
    return out


# ---------------------------------------------------------------- built-in invariants


def check_invariants(trace: TurnTrace, pack: PackView) -> List[CheckResult]:
    """Checks that hold for every turn, whatever the scenario expects."""
    out: List[CheckResult] = []
    out.append(_fail("turn_completed", trace.error) if trace.error else _ok("turn_completed"))
    out.append(_ok("answer_present") if trace.answer.strip() else _fail("answer_present", "the turn produced no reply"))
    if trace.task_calls > pack.max_agents:
        out.append(_fail("task_call_cap", f"{trace.task_calls} task calls, cap is {pack.max_agents}"))
    else:
        out.append(_ok("task_call_cap", f"{trace.task_calls} of {pack.max_agents}"))
    # Hidden agents run only when routing sends work to them: the agent a pack
    # fixed route picked for this turn is allowed. A caller's pick or a main
    # agent hand-off to a hidden agent still fails.
    routed_to = (
        str(trace.route_agent)
        if trace.route_agent and str(trace.route or "").startswith("fixed_route:")
        else None
    )
    ran_hidden = [a for a in trace.agents if a in pack.hidden and a != routed_to]
    if ran_hidden:
        out.append(_fail("hidden_agents_not_run", f"hidden agent(s) ran: {ran_hidden}"))
    elif routed_to and routed_to in pack.hidden and routed_to in trace.agents:
        out.append(_ok("hidden_agents_not_run", f"{routed_to} reached by {trace.route}"))
    else:
        out.append(_ok("hidden_agents_not_run"))
    unknown = [a for a in trace.agents if a not in pack.titles]
    out.append(_fail("known_agents_only", f"unknown agent(s) ran: {unknown}") if unknown else _ok("known_agents_only"))
    bad_titles = [
        p.get("agent_id")
        for p in trace.provenance
        if str(p.get("agent_id")) in pack.titles and p.get("agent_title") != pack.titles[str(p.get("agent_id"))]
    ]
    out.append(
        _fail("provenance_titles", f"provenance does not carry the pack title for {bad_titles}")
        if bad_titles
        else _ok("provenance_titles")
    )
    out.append(
        _fail("no_subagent_tokens", f"subagent tokens reached the stream: {trace.subagent_token_leaks[:3]}")
        if trace.subagent_token_leaks
        else _ok("no_subagent_tokens")
    )
    out.append(check_route_audited(trace))
    out.append(check_turn_tasks_recorded(trace))
    if trace.script_problems:
        out.append(_fail("fake_script", "; ".join(trace.script_problems)))
    return out


_ROUTE_EVENT_FOR = {
    "user_selected": "route.user_selected",
    "model_classified": "route.classified",
    "fixed_route": "route.fixed",
    "default_agent": "route.default",
    "main_agent": "route.main_agent",
}


def check_route_audited(trace: TurnTrace) -> CheckResult:
    """The turn's route has a matching ``route.*`` audit record, written last."""
    if trace.route is None:
        return _skip("route_audited", "the turn has no route decision")
    want = _ROUTE_EVENT_FOR.get(trace.route.partition(":")[0])
    if not trace.route_events:
        return _fail("route_audited", f"no route.* audit record; expected {want}")
    if trace.route_events[-1] != want:
        return _fail("route_audited", f"expected {want} last, got {trace.route_events}")
    return _ok("route_audited", ", ".join(trace.route_events))


def check_hidden_pick_refused(trace: TurnTrace, turn: Turn, pack: PackView) -> List[CheckResult]:
    """A pick of a hidden agent is refused, audited, and the turn routed instead."""
    pick = turn.explicit_agent
    if not pick or pick not in pack.hidden:
        return []
    if trace.route == "user_selected" or pick in trace.agents:
        return [_fail("hidden_pick_refused", f"hidden agent {pick!r} took the turn (route {trace.route})")]
    if "route.rejected" not in trace.route_events:
        return [_fail("hidden_pick_refused", f"no route.rejected record; got {trace.route_events}")]
    return [_ok("hidden_pick_refused", f"routed {trace.route}")]


def check_turn_tasks_recorded(trace: TurnTrace) -> CheckResult:
    """Every hand-off in the audit log has one stored turn task with the same final state."""
    audited = {t.task_id: t.final_state for t in [*trace.tasks, *trace.rejected_tasks]}
    stored = {str(r.get("task_id")): str(r.get("state")) for r in trace.turn_tasks}
    if len(stored) != len(trace.turn_tasks):
        return _fail("turn_tasks_recorded", "duplicate task ids in the stored turn tasks")
    if stored != audited:
        return _fail("turn_tasks_recorded", f"stored {stored}, audit log {audited}")
    return _ok("turn_tasks_recorded", f"{len(stored)} hand-off(s)")


def check_guardrail_flag(trace: TurnTrace, turn: Turn) -> List[CheckResult]:
    """The input guardrail raised the flag the turn expects, from the user's text."""
    flag = turn.input.guardrail_flag if turn.input is not None else None
    if flag is None:
        return []
    if flag in trace.guardrail_flags:
        return [_ok("guardrail_flag", flag)]
    return [_fail("guardrail_flag", f"expected {flag!r} raised, got {trace.guardrail_flags}")]


# ---------------------------------------------------------------- expectations


def check_route(trace: TurnTrace, expect: TurnExpectation) -> CheckResult:
    if expect.route is None:
        return _skip("route")
    if trace.route == expect.route:
        return _ok("route", trace.route or "")
    return _fail("route", f"expected {expect.route}, got {trace.route}")


def check_agents(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    ran = set(trace.agents)
    out: List[CheckResult] = []
    if expect.agents_exactly is not None:
        want = set(expect.agents_exactly)
        out.append(
            _ok("agents_exactly", str(_set(ran)))
            if ran == want
            else _fail("agents_exactly", f"expected {_set(want)}, got {_set(ran)}")
        )
    if expect.agents_all_of:
        missing = set(expect.agents_all_of) - ran
        out.append(_fail("agents_all_of", f"missing {_set(missing)}; ran {_set(ran)}") if missing else _ok("agents_all_of"))
    if expect.agents_any_of:
        hit = set(expect.agents_any_of) & ran
        out.append(_ok("agents_any_of", str(_set(hit))) if hit else _fail("agents_any_of", f"none of {expect.agents_any_of} ran; ran {_set(ran)}"))
    if expect.agents_forbidden:
        bad = set(expect.agents_forbidden) & ran
        out.append(_fail("agents_forbidden", f"forbidden agent(s) ran: {_set(bad)}") if bad else _ok("agents_forbidden"))
    return out


def check_task_calls(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    out: List[CheckResult] = []
    n = trace.task_calls
    if expect.min_task_calls is not None:
        out.append(_ok("min_task_calls", str(n)) if n >= expect.min_task_calls else _fail("min_task_calls", f"{n} < {expect.min_task_calls}"))
    if expect.max_task_calls is not None:
        out.append(_ok("max_task_calls", str(n)) if n <= expect.max_task_calls else _fail("max_task_calls", f"{n} > {expect.max_task_calls}"))
    return out


def check_continuity(trace: TurnTrace, expect: TurnExpectation, previous: Sequence[TurnTrace]) -> List[CheckResult]:
    ref = expect.same_agents_as_turn
    if ref is None:
        return []
    if ref.turn > len(previous):
        return [_fail("same_agents_as_turn", f"turn {ref.turn} has no trace")]
    earlier = set(previous[ref.turn - 1].agents)
    now = set(trace.agents)
    if ref.mode == "equal":
        ok = now == earlier
    elif ref.mode == "subset":
        ok = bool(now) and now <= earlier
    else:
        ok = bool(now & earlier)
    detail = f"{ref.mode}: turn {ref.turn} {_set(earlier)} vs now {_set(now)}"
    return [_ok("same_agents_as_turn", detail) if ok else _fail("same_agents_as_turn", detail)]


def check_task_states(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if not expect.task_states:
        return []
    seen = trace.final_states()
    wrong = {a: seen.get(a) for a, s in expect.task_states.items() if seen.get(a) != s}
    if wrong:
        return [_fail("task_states", f"expected {dict(expect.task_states)}, got {wrong}")]
    return [_ok("task_states")]


def check_notices(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if expect.notices is None:
        return []
    want: Dict[str, Optional[List[str]]] = {}
    for item in expect.notices:
        if isinstance(item, NoticeExpectation):
            want[item.code] = list(item.agent_ids) or None
        else:
            want[item] = None
    got_codes = set(trace.notice_codes)
    out: List[CheckResult] = []
    if got_codes != set(want):
        out.append(_fail("notices", f"expected {_set(want)}, got {_set(got_codes)}"))
    else:
        out.append(_ok("notices", str(_set(got_codes))))
    for code, agent_ids in want.items():
        if agent_ids is None or code not in got_codes:
            continue
        seen = set()
        for n in trace.notices:
            if n.get("code") == code:
                seen.update(n.get("agent_ids") or [])
        if seen != set(agent_ids):
            out.append(_fail(f"notice_agents:{code}", f"expected {_set(agent_ids)}, got {_set(seen)}"))
        else:
            out.append(_ok(f"notice_agents:{code}"))
    return out


def check_answer(trace: TurnTrace, expect: TurnExpectation, pack: PackView) -> List[CheckResult]:
    answer = trace.answer
    spec = expect.answer
    out: List[CheckResult] = []
    no_slug = spec.no_slug_leak if spec is not None else True
    if no_slug:
        leaks = leaked_ids(answer, [*pack.agent_ids, MAIN_AGENT_ID])
        out.append(_fail("no_agent_ids_in_answer", f"answer names agent id(s) {leaks}") if leaks else _ok("no_agent_ids_in_answer"))
    if spec is None:
        return out
    for pattern in spec.must_mention:
        out.append(
            _ok(f"must_mention:{pattern}")
            if text_matches(pattern, answer)
            else _fail(f"must_mention:{pattern}", f"not found in answer: {answer[:160]!r}")
        )
    for pattern in spec.must_not_mention:
        out.append(
            _fail(f"must_not_mention:{pattern}", f"found in answer: {answer[:160]!r}")
            if text_matches(pattern, answer)
            else _ok(f"must_not_mention:{pattern}")
        )
    return out


def check_provenance(trace: TurnTrace, expect: TurnExpectation, pack: PackView) -> List[CheckResult]:
    spec = expect.provenance
    if spec is None:
        return []
    by_agent: Dict[str, List[str]] = {}
    for p in trace.provenance:
        by_agent.setdefault(str(p.get("agent_id")), []).append(str(p.get("state")))
    out: List[CheckResult] = []
    for agent_id in spec.must_cite:
        ok = "completed" in by_agent.get(agent_id, [])
        out.append(_ok(f"cites:{agent_id}") if ok else _fail(f"cites:{agent_id}", f"no completed provenance entry; have {by_agent}"))
    for agent_id in spec.must_not_cite:
        out.append(_fail(f"does_not_cite:{agent_id}", f"provenance has {by_agent[agent_id]}") if agent_id in by_agent else _ok(f"does_not_cite:{agent_id}"))
    for agent_id in spec.missing:
        states = by_agent.get(agent_id, [])
        if not states or all(s == "completed" for s in states):
            out.append(_fail(f"missing:{agent_id}", f"expected a failed hand-off in provenance; have {states}"))
            continue
        title = pack.titles.get(agent_id, agent_id)
        if title.lower() in trace.answer.lower():
            out.append(_ok(f"missing:{agent_id}", f"answer names {title!r}"))
        else:
            out.append(_fail(f"missing:{agent_id}", f"answer does not name the missing agent {title!r}"))
    return out


def check_deliberation(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if expect.deliberation is None:
        return []
    ran = "deliberation" in trace.nodes
    return [_ok("deliberation") if ran == expect.deliberation else _fail("deliberation", f"expected {expect.deliberation}, got {ran}")]


def check_model_calls_before_route(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if expect.model_calls_before_route is None:
        return []
    n = trace.model_calls_before_route
    want = expect.model_calls_before_route
    return [_ok("model_calls_before_route", str(n)) if n == want else _fail("model_calls_before_route", f"expected {want}, got {n}")]


def check_budget(trace: TurnTrace, expect: TurnExpectation, usd: float) -> List[CheckResult]:
    b = expect.budget
    if b is None:
        return []
    out: List[CheckResult] = []
    if b.latency_ms_p95 is not None:
        out.append(_ok("budget:latency_ms") if trace.latency_ms <= b.latency_ms_p95 else _fail("budget:latency_ms", f"{trace.latency_ms:.0f} > {b.latency_ms_p95}"))
    if b.tokens is not None:
        out.append(_ok("budget:tokens") if trace.tokens <= b.tokens else _fail("budget:tokens", f"{trace.tokens} > {b.tokens}"))
    if b.usd is not None:
        out.append(_ok("budget:usd") if usd <= b.usd else _fail("budget:usd", f"{usd:.6f} > {b.usd}"))
    if b.model_calls is not None:
        out.append(_ok("budget:model_calls") if trace.model_calls <= b.model_calls else _fail("budget:model_calls", f"{trace.model_calls} > {b.model_calls}"))
    if b.prompt_chars is not None:
        out.append(
            _ok("budget:prompt_chars")
            if trace.prompt_chars <= b.prompt_chars
            else _fail("budget:prompt_chars", f"{trace.prompt_chars} > {b.prompt_chars}")
        )
    return out


def check_cancelled(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if expect.cancelled is None:
        return []
    if expect.cancelled and not trace.cancelled:
        return [_fail("cancelled", "expected the turn to be cancelled")]
    if not expect.cancelled and trace.cancelled:
        return [_fail("cancelled", "turn was cancelled unexpectedly")]
    return [_ok("cancelled", "yes" if trace.cancelled else "no")]


def check_error_matches(trace: TurnTrace, expect: TurnExpectation) -> List[CheckResult]:
    if expect.error_matches is None:
        return []
    err = trace.error or ""
    if not err:
        return [_fail("error_matches", f"expected error matching {expect.error_matches!r}, got none")]
    if text_matches(expect.error_matches, err):
        return [_ok("error_matches", err[:120])]
    return [_fail("error_matches", f"expected {expect.error_matches!r}, got {err[:160]!r}")]


def check_turn(
    trace: TurnTrace,
    turn: Turn,
    pack: PackView,
    previous: Sequence[TurnTrace] = (),
    usd: float = 0.0,
) -> List[CheckResult]:
    """Runs every invariant and every expectation set on ``turn``."""
    expect = turn.expect
    results: List[CheckResult] = []
    # Cancelled / expected-error turns skip the usual "finished with a reply" invariants.
    if expect.cancelled:
        results.append(_ok("turn_completed", "cancelled") if trace.cancelled else _fail("turn_completed", "expected cancel"))
        results.append(_ok("answer_present", "cancelled turn"))
    elif expect.error_matches is not None:
        results.extend(check_error_matches(trace, expect))
        results.append(_ok("answer_present", "error turn"))
    else:
        results.extend(check_invariants(trace, pack))
    if expect.cancelled is not None and not expect.cancelled:
        results.extend(check_cancelled(trace, expect))
    elif expect.cancelled:
        results.extend(check_cancelled(trace, expect))
    results += check_hidden_pick_refused(trace, turn, pack)
    results += check_guardrail_flag(trace, turn)
    results.append(check_route(trace, expect))
    results += check_agents(trace, expect)
    results += check_task_calls(trace, expect)
    results += check_continuity(trace, expect, previous)
    results += check_task_states(trace, expect)
    results += check_notices(trace, expect)
    if not expect.cancelled and expect.error_matches is None:
        results += check_answer(trace, expect, pack)
    results += check_provenance(trace, expect, pack)
    results += check_deliberation(trace, expect)
    results += check_model_calls_before_route(trace, expect)
    results += check_budget(trace, expect, usd)
    if turn.judge is not None:
        # Soft placeholder; the driver replaces this when --judge is on.
        results.append(_skip(f"judge:{turn.judge.rubric}", "judge not enabled for this run"))
    return results


__all__ = [
    "CheckResult",
    "CheckStatus",
    "PackView",
    "check_agents",
    "check_answer",
    "check_budget",
    "check_cancelled",
    "check_continuity",
    "check_deliberation",
    "check_error_matches",
    "check_guardrail_flag",
    "check_hidden_pick_refused",
    "check_invariants",
    "check_model_calls_before_route",
    "check_notices",
    "check_provenance",
    "check_route",
    "check_route_audited",
    "check_task_calls",
    "check_task_states",
    "check_turn",
    "check_turn_tasks_recorded",
    "leaked_ids",
    "text_matches",
]
