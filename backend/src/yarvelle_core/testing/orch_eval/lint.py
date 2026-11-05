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

"""Checks a scenario against the eval pack it names.

Schema validation catches malformed files; this catches well-formed files
that cannot run: agent ids the pack does not have, hidden agents expected to
answer, and fixed routes the pack does not declare.
"""

from __future__ import annotations

from typing import List, Set

from yarvelle_core.engine.orchestration.routing import BUILTIN_DOCUMENT_ROUTE_ID
from yarvelle_core.testing.orch_eval.pack import EvalPack
from yarvelle_core.testing.orch_eval.schema import NoticeExpectation, Scenario

FALLBACK_REASONS = ("model_unavailable", "main_agent_failed")


def lint_against_pack(scenario: Scenario, pack: EvalPack) -> List[str]:
    """Returns the problems found, as ``turn N: ...`` strings. Empty means valid."""
    problems: List[str] = []
    if scenario.pack != pack.id:
        return [f"scenario names pack {scenario.pack!r}, but the pack loaded is {pack.id!r}"]
    known: Set[str] = set(pack.agent_ids)
    hidden: Set[str] = set(pack.hidden_ids)
    # Without pack routes only core's built-in document route can fire.
    route_ids: List[str] = [BUILTIN_DOCUMENT_ROUTE_ID] if scenario.routing == "builtin" else list(pack.route_ids)
    if scenario.limits is not None and scenario.limits.max_agents is not None and scenario.limits.max_agents > 16:
        problems.append("limits.max_agents is above the runtime maximum of 16")

    for number, turn in enumerate(scenario.turns, start=1):
        where = f"turn {number}"

        def unknown(ids: List[str], what: str) -> None:
            bad = sorted(set(ids) - known)
            if bad:
                problems.append(f"{where}: {what} names agent(s) not in pack {pack.id!r}: {bad}")

        def not_hidden(ids: List[str], what: str) -> None:
            bad = sorted(set(ids) & hidden)
            if bad:
                problems.append(f"{where}: {what} names hidden agent(s) {bad}; hidden agents never answer")

        expect = turn.expect
        flag = turn.input.guardrail_flag if turn.input is not None else None
        if flag is not None:
            if flag not in pack.flag_words:
                problems.append(f"{where}: guardrail_flag {flag!r} is not listed under the pack's guardrail_flags")
            elif flag not in pack.flags_for(turn.user):
                problems.append(f"{where}: the user text does not raise guardrail_flag {flag!r} (words: {pack.flag_words[flag]})")
        if turn.explicit_agent is not None:
            unknown([turn.explicit_agent], "explicit_agent")
            if turn.explicit_agent in hidden and expect.route == "user_selected":
                problems.append(
                    f"{where}: explicit_agent {turn.explicit_agent!r} is hidden; a hidden pick is refused, "
                    "so the turn cannot route user_selected"
                )
        required = [*(expect.agents_exactly or []), *expect.agents_all_of, *expect.agents_any_of]
        unknown(required, "expected agents")
        not_hidden(required, "expected agents")
        unknown(expect.agents_forbidden, "agents_forbidden")
        unknown(list(expect.task_states), "task_states")
        not_hidden(list(expect.task_states), "task_states")
        for notice in expect.notices or []:
            if isinstance(notice, NoticeExpectation):
                unknown(list(notice.agent_ids), f"notice {notice.code}")
        if expect.provenance is not None:
            cited = [*expect.provenance.must_cite, *expect.provenance.missing]
            unknown(cited, "provenance")
            not_hidden(cited, "provenance")
            unknown(expect.provenance.must_not_cite, "provenance.must_not_cite")
        if expect.route is not None:
            kind, _, value = expect.route.partition(":")
            if kind == "fixed_route" and value not in route_ids:
                problems.append(f"{where}: route names fixed route {value!r}; the graph has {route_ids}")
            if kind == "model_classified" and scenario.routing == "hybrid":
                problems.append(f"{where}: route model_classified needs routing 'classifier' or 'builtin'")
            if kind == "main_agent" and scenario.routing != "hybrid":
                problems.append(f"{where}: route main_agent needs routing 'hybrid'")
            if kind == "default_agent" and value not in FALLBACK_REASONS:
                problems.append(f"{where}: default_agent reason must be one of {list(FALLBACK_REASONS)}, got {value!r}")
            if kind == "user_selected" and turn.explicit_agent is None:
                problems.append(f"{where}: route user_selected needs explicit_agent")
        if turn.fake is not None:
            for step in turn.fake.main:
                unknown(list(step.task or []), "fake main task")
                if step.route is not None:
                    unknown([step.route], "fake main route")
                    if scenario.routing == "hybrid":
                        problems.append(f"{where}: a fake 'route' step needs routing 'classifier' or 'builtin'")
            unknown(list(turn.fake.agents), "fake agents")
            not_hidden(list(turn.fake.agents), "fake agents")

    for fault in scenario.faults:
        where = f"fault turn {fault.turn}"
        if fault.agent and fault.agent not in ("main", "*"):
            if fault.agent not in known:
                problems.append(f"{where}: agent {fault.agent!r} is not in pack {pack.id!r}")
            elif fault.agent in hidden and fault.mode not in ("inject",):
                # inject may target a visible agent whose reply mentions the hidden one
                pass
        if fault.mode == "truncate" and fault.tool is None:
            problems.append(f"{where}: truncate fault needs a tool name")
    return problems


__all__ = ["FALLBACK_REASONS", "lint_against_pack"]
