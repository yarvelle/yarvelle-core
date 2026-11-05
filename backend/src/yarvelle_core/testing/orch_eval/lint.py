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
        if turn.explicit_agent is not None:
            unknown([turn.explicit_agent], "explicit_agent")
            not_hidden([turn.explicit_agent], "explicit_agent")
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
            if kind == "fixed_route" and value not in pack.route_ids:
                problems.append(f"{where}: route names fixed route {value!r}; pack has {pack.route_ids}")
            if kind == "default_agent" and value not in FALLBACK_REASONS:
                problems.append(f"{where}: default_agent reason must be one of {list(FALLBACK_REASONS)}, got {value!r}")
            if kind == "user_selected" and turn.explicit_agent is None:
                problems.append(f"{where}: route user_selected needs explicit_agent")
        if turn.fake is not None:
            for step in turn.fake.main:
                unknown(list(step.task or []), "fake main task")
            unknown(list(turn.fake.agents), "fake agents")
            not_hidden(list(turn.fake.agents), "fake agents")
    return problems


__all__ = ["FALLBACK_REASONS", "lint_against_pack"]
