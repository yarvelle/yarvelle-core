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

"""Rule-based convergence gate for multi-agent deliberation.

Enforces ADR 0001 §2.4:
- Convergence is strictly rule-based: advances to Synthesize when:
  (1) 0 open CONFLICT and 0 open AMEND critiques remain, OR
  (2) round_num reaches max_rounds, OR
  (3) wall-clock or token budget is exhausted.
- Self-reported confidence NEVER drives convergence, weighting, or control flow.
- Selective revision: targets ONLY agents challenged by open CONFLICT or AMEND critiques.
"""

from __future__ import annotations

import logging
import time
from typing import List, NamedTuple, Optional, Sequence

from yarvelle_core.schemas.plan import DeliberationBudget
from yarvelle_core.workflows.state import AgentProposal, CritiqueStance, PeerCritique

logger = logging.getLogger(__name__)


class ConvergenceDecision(NamedTuple):
    """Decision produced by ConvergenceGate evaluation."""

    next_node: str
    reason: str
    target_agents: List[str]
    converged: bool = False


def evaluate_convergence_gate(
    critiques: Sequence[PeerCritique],
    round_num: int,
    max_rounds: int = 2,
    budget_remaining: bool = True,
    proposals: Optional[Sequence[AgentProposal]] = None,
    budget: Optional[DeliberationBudget] = None,
    start_time: Optional[float] = None,
    total_tokens: int = 0,
    active_agents: Optional[Sequence[str]] = None,
) -> ConvergenceDecision:
    """Evaluates rule-based convergence for the deliberation round.

    Invariants:
    1. Self-reported confidence in proposals is NEVER read or used to decide convergence.
    2. Zero open CONFLICT and zero open AMEND critiques -> Converged to Synthesize.
    3. round_num >= max_rounds -> advances to Synthesize with max_rounds_reached.
    4. Budget exhaustion (wall-clock or token) -> advances to Synthesize with budget_exhausted.
    5. Open critiques with budget and rounds remaining -> routes to selective_revise targeting
       only the specific agents with open critiques.
    """
    effective_max_rounds = budget.max_rounds if budget is not None else max_rounds

    open_conflicts = [
        c for c in critiques
        if not c.resolved and c.stance == CritiqueStance.CONFLICT
    ]
    open_amends = [
        c for c in critiques
        if not c.resolved and c.stance == CritiqueStance.AMEND
    ]
    blocking_critiques = open_conflicts + open_amends

    # 1. No blocking critiques -> Converged
    if not blocking_critiques:
        logger.info("ConvergenceGate: Deliberation converged with 0 open conflicts and amends.")
        return ConvergenceDecision(
            next_node="synthesize",
            reason="converged",
            target_agents=[],
            converged=True,
        )

    # 2. Maximum rounds reached
    if round_num >= effective_max_rounds:
        logger.info(
            "ConvergenceGate: Deliberation reached max_rounds (%d >= %d). Advancing to synthesize.",
            round_num,
            effective_max_rounds,
        )
        return ConvergenceDecision(
            next_node="synthesize",
            reason="max_rounds_reached",
            target_agents=[],
            converged=False,
        )

    # 3. Explicit budget_remaining flag
    if not budget_remaining:
        logger.info("ConvergenceGate: Deliberation budget exhausted. Advancing to synthesize.")
        return ConvergenceDecision(
            next_node="synthesize",
            reason="budget_exhausted",
            target_agents=[],
            converged=False,
        )

    # 4. Wall-clock and token budget inspection
    if budget is not None:
        if start_time is not None:
            elapsed_s = time.time() - start_time
            if elapsed_s >= budget.max_wall_clock_s:
                logger.info(
                    "ConvergenceGate: Wall-clock limit exceeded (%.2fs >= %.2fs). Advancing to synthesize.",
                    elapsed_s,
                    budget.max_wall_clock_s,
                )
                return ConvergenceDecision(
                    next_node="synthesize",
                    reason="wall_clock_exhausted",
                    target_agents=[],
                    converged=False,
                )

        if total_tokens > 0 and total_tokens >= budget.max_total_tokens:
            logger.info(
                "ConvergenceGate: Token budget exceeded (%d >= %d). Advancing to synthesize.",
                total_tokens,
                budget.max_total_tokens,
            )
            return ConvergenceDecision(
                next_node="synthesize",
                reason="token_budget_exhausted",
                target_agents=[],
                converged=False,
            )

    # 5. Open blocking critiques remain and budget allows revision
    targeted_set = {c.target_agent_id for c in blocking_critiques}
    if active_agents is not None:
        targeted_set = targeted_set.intersection(set(active_agents))
    targeted = sorted(list(targeted_set))

    logger.info(
        "ConvergenceGate: Round %d has %d open critique(s). Targeting agents: %s for selective revision.",
        round_num,
        len(blocking_critiques),
        targeted,
    )
    return ConvergenceDecision(
        next_node="selective_revise",
        reason="revision_needed",
        target_agents=targeted,
        converged=False,
    )


class ConvergenceGate:
    """Class wrapper for convergence gate evaluation."""

    evaluate = staticmethod(evaluate_convergence_gate)
