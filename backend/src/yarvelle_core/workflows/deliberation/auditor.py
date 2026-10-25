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

"""Deterministic constraint budget auditor for multi-agent deliberation.

Enforces ADR 0001 §2.5:
- Deterministic arithmetic summation of resource claims per SharedConstraint.
- Limits must originate strictly from user or profile data; model cannot guess.
- Unknown limits (limit_value is None) are skipped without error.
- Unit mismatch fails validation without attempting conversions.
- Overbudget condition emits CONFLICT critique targeted at each contributing specialist.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence, Union

from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.workflows.state import AgentProposal, CritiqueStance, PeerCritique

logger = logging.getLogger(__name__)


class UnitMismatchError(ValueError):
    """Raised when an agent's resource claim unit does not match the shared constraint unit."""


class BudgetAuditor:
    """Deterministic constraint budget auditor verifying resource claims against limits."""

    def __init__(self) -> None:
        self.skipped_constraints: List[str] = []

    def audit(
        self,
        constraints: Sequence[SharedConstraint],
        proposals: Union[Sequence[AgentProposal], Dict[str, AgentProposal]],
        round_num: int = 1,
        moderator_id: str = "orchestrator",
    ) -> List[PeerCritique]:
        """Audits resource claims against user/profile limits deterministically.

        Invariants:
        1. Checks only constraints where limit_value is not None.
        2. Unknown limits (limit_value is None) are recorded in skipped_constraints.
        3. Fails validation on unit mismatch without guessing conversions.
        4. Overbudget condition emits CONFLICT critique targeted at each contributing specialist.
        """
        self.skipped_constraints = []
        critiques: List[PeerCritique] = []

        if isinstance(proposals, dict):
            proposals_dict: Dict[str, AgentProposal] = proposals
        else:
            proposals_dict = {p.agent_id: p for p in proposals}

        for constraint in constraints:
            cid = constraint.id
            if constraint.limit_value is None:
                self.skipped_constraints.append(cid)
                logger.info(
                    "BudgetAuditor: Skipping constraint '%s' because limit_value is None.",
                    cid,
                )
                continue

            limit = constraint.limit_value
            unit = constraint.unit
            limit_source = constraint.limit_source or "user"

            # Check unit match across all proposals
            for aid, proposal in proposals_dict.items():
                if cid in proposal.resource_claims:
                    claim_unit = proposal.resource_claim_units.get(cid)
                    if claim_unit is None or claim_unit != unit:
                        raise UnitMismatchError(
                            f"Unit mismatch for constraint '{cid}': expected '{unit}', "
                            f"got '{claim_unit}' from agent '{aid}'. Conversions are not guessed."
                        )

            # Sum claims deterministically
            contributing = [
                p for p in proposals_dict.values()
                if p.resource_claims.get(cid, 0.0) > 0
            ]
            total_claimed = sum(p.resource_claims.get(cid, 0.0) for p in contributing)

            if (total_claimed - limit) > 1e-9:
                overage = round(total_claimed - limit, 4)
                logger.info(
                    "BudgetAuditor: Constraint '%s' overbudget: total claimed %s %s exceeds limit %s %s.",
                    cid,
                    total_claimed,
                    unit,
                    limit,
                    unit,
                )
                for p in contributing:
                    claim_val = p.resource_claims.get(cid, 0.0)
                    critiques.append(
                        PeerCritique(
                            reviewer_agent_id=moderator_id,
                            target_agent_id=p.agent_id,
                            round_num=round_num,
                            stance=CritiqueStance.CONFLICT,
                            issue_type="resource_overbudget",
                            critique=(
                                f"Resource overbudget for constraint '{cid}': total claimed "
                                f"{total_claimed} {unit} exceeds {limit_source} limit of "
                                f"{limit} {unit} (overage: {overage} {unit})."
                            ),
                            proposed_resolution=(
                                f"Coordinate with peers to reduce allocation for '{cid}' "
                                f"(current claim: {claim_val} {unit}) so cumulative claims "
                                f"do not exceed {limit} {unit}."
                            ),
                            resolved=False,
                        )
                    )

        return critiques
