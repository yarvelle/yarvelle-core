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

"""Blackboard state manager for multi-agent deliberation.

Manages scoped proposal recording, peer critiques, and Phase 1 invariants:
- Staged write actions are dropped in Phase 1.
- In-memory history maintained per round.
"""

from __future__ import annotations

import logging
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.scope.context import ScopeContext, is_scope_granted
from yarvelle_core.workflows.state import AgentProposal, PeerCritique, StagedAction, TypedClaim

logger = logging.getLogger(__name__)


def is_same_domain(scope_a: str, scope_b: str) -> bool:
    """Returns True if both scopes belong to the same top-level domain hierarchy."""
    if not isinstance(scope_a, str) or not isinstance(scope_b, str):
        return False
    sa = scope_a.strip()
    sb = scope_b.strip()
    if not sa or not sb:
        return False
    prefix_a = sa.split(".")[0]
    prefix_b = sb.split(".")[0]
    if not prefix_a or not prefix_b:
        return False
    if "/" in prefix_a or "\\" in prefix_a or "/" in prefix_b or "\\" in prefix_b:
        return False
    if sa == sb:
        return True
    return prefix_a == prefix_b


class BlackboardManager:
    """Scoped blackboard manager storing proposals, critiques, and constraint states."""

    def __init__(
        self,
        panel_id: Optional[str] = None,
        shared_constraints: Optional[List[SharedConstraint]] = None,
    ) -> None:
        self.panel_id = panel_id
        self.shared_constraints: List[SharedConstraint] = list(shared_constraints or [])
        self.proposals: Dict[int, Dict[str, AgentProposal]] = {}  # round_num -> agent_id -> proposal
        self.critiques: Dict[int, List[PeerCritique]] = {}         # round_num -> list of critiques
        self.active_proposals: Dict[str, AgentProposal] = {}      # agent_id -> latest proposal
        self.missing_agents: List[str] = []
        self.degraded: bool = False
        self.recorded_cross_reads: List[Dict[str, Any]] = []

    def record_proposal(self, proposal: AgentProposal) -> None:
        """Stores a proposal for its round and updates active_proposals."""
        r = proposal.round_num
        if r not in self.proposals:
            self.proposals[r] = {}
        self.proposals[r][proposal.agent_id] = proposal
        self.active_proposals[proposal.agent_id] = proposal

    def get_active_staged_actions(self) -> List[StagedAction]:
        """Returns active staged actions aggregated across all active proposals."""
        actions: List[StagedAction] = []
        for p in self.active_proposals.values():
            if p.staged_actions:
                actions.extend(p.staged_actions)
        return actions

    def record_critiques(self, round_num: int, critiques: List[PeerCritique]) -> None:
        """Appends peer and auditor critiques for the specified round."""
        if round_num not in self.critiques:
            self.critiques[round_num] = []
        self.critiques[round_num].extend(critiques)

    def filter_scoped_proposals(
        self,
        reader_agent_id: str,
        reader_scope: str = "",
        *,
        declared_reads: Optional[Collection[str]] = None,
        granted_scopes: Optional[Collection[str]] = None,
        round_num: int = 1,
    ) -> Tuple[Dict[str, AgentProposal], List[Dict[str, Any]]]:
        """Pure filtering function building reader's scoped blackboard view.

        Enforces ADR 0001 §2.3 Rules 1-4:
        - Rule 1: Same-domain specialists see full proposals.
        - Rule 2: Cross-domain specialists receive zero free-text summaries/recommendations.
        - Rule 3: Cross-domain specialists see ONLY structured TypedClaim items.
        - Rule 4: Claim reading requires BOTH declared_reads AND an active grant for source scope;
                  missing either withholds the claim and emits an 'undisclosed_constraint' indicator.

        Returns:
            Tuple of (scoped_proposals_dict, cross_read_events_to_audit).
        """
        if not reader_scope and reader_agent_id in self.active_proposals:
            reader_scope = self.active_proposals[reader_agent_id].scope

        ctx = ScopeContext.get()
        if declared_reads is None:
            active_declared = ctx.declared_reads if ctx else frozenset()
        else:
            active_declared = frozenset(declared_reads)
        if granted_scopes is None:
            active_granted = ctx.granted_scopes if ctx else frozenset()
        else:
            active_granted = frozenset(granted_scopes)

        if not reader_scope and ctx and ctx.scope:
            reader_scope = ctx.scope

        scoped_proposals: Dict[str, AgentProposal] = {}
        cross_read_events: List[Dict[str, Any]] = []

        for aid, prop in self.active_proposals.items():
            if aid == reader_agent_id:
                continue

            # Rule 1: Same-domain panels see full proposals
            # Fail closed: missing or empty reader_scope is treated as cross-domain (ADR 0001 §2.3)
            if reader_scope and is_same_domain(reader_scope, prop.scope):
                scoped_proposals[aid] = prop.model_copy(deep=True)
                continue

            # Rule 2: Cross-domain panels: strip free-text summaries, recommendations, staged actions
            # Rule 3 & 4: Only structured TypedClaim items, requiring BOTH declared_reads AND active grant
            permitted_claims: List[TypedClaim] = []
            withheld_count = 0

            for claim in prop.exported_claims:
                # ADR 0001 §2.3: Validate that claim source_scope belongs to the proposer's owned scope hierarchy
                if claim.source_scope:
                    if not is_same_domain(claim.source_scope, prop.scope):
                        logger.warning(
                            "Spoofed or invalid claim source_scope '%s' does not match proposal scope '%s' for agent '%s'; withholding.",
                            claim.source_scope,
                            prop.scope,
                            prop.agent_id,
                        )
                        withheld_count += 1
                        continue
                    claim_scope = claim.source_scope
                else:
                    claim_scope = prop.scope

                has_grant = is_scope_granted(claim_scope, active_granted)
                has_declaration = is_scope_granted(claim_scope, active_declared)

                if has_grant and has_declaration:
                    claim_copy = claim.model_copy(deep=True)
                    if not claim_copy.source_scope:
                        claim_copy.source_scope = prop.scope
                    permitted_claims.append(claim_copy)
                else:
                    withheld_count += 1

            final_claims: List[TypedClaim] = list(permitted_claims)
            if withheld_count > 0:
                final_claims.append(
                    TypedClaim(
                        kind="boolean",
                        key="undisclosed_constraint",
                        value=None,
                        source_scope=prop.scope,
                    )
                )

            effective_round = round_num or prop.round_num
            if permitted_claims:
                cross_read_events.append({
                    "reader_agent_id": reader_agent_id,
                    "reader_scope": reader_scope,
                    "target_agent_id": prop.agent_id,
                    "target_scope": prop.scope,
                    "claim_keys": sorted([c.key for c in permitted_claims]),
                    "round_num": effective_round,
                })

            scoped_proposals[aid] = AgentProposal(
                agent_id=prop.agent_id,
                round_num=prop.round_num,
                scope=prop.scope,
                summary="",
                recommendations=[],
                resource_claims={},
                resource_claim_units={},
                exported_claims=final_claims,
                dependencies=[],
                staged_actions=[],
                confidence=prop.confidence,
                provenance=list(prop.provenance),
                tainted=prop.tainted,
            )

        self.recorded_cross_reads.extend(cross_read_events)
        return scoped_proposals, cross_read_events

    async def get_scoped_proposals_for(
        self,
        reader_agent_id: str,
        reader_scope: str = "",
        *,
        declared_reads: Optional[Collection[str]] = None,
        granted_scopes: Optional[Collection[str]] = None,
        round_num: int = 1,
        session: Optional[AsyncSession] = None,
        session_factory: Optional[Any] = None,
        profile_id: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, AgentProposal]:
        """Returns peer proposals visible to the reader agent and records audit events."""
        scoped_proposals, events_to_audit = self.filter_scoped_proposals(
            reader_agent_id=reader_agent_id,
            reader_scope=reader_scope,
            declared_reads=declared_reads,
            granted_scopes=granted_scopes,
            round_num=round_num,
        )

        for ev in events_to_audit:
            try:
                from yarvelle_core.audit.hash_chain import record_scope_cross_read_audit

                await record_scope_cross_read_audit(
                    session=session,
                    session_factory=session_factory,
                    reader_agent_id=ev["reader_agent_id"],
                    reader_scope=ev["reader_scope"],
                    target_agent_id=ev["target_agent_id"],
                    target_scope=ev["target_scope"],
                    claim_keys=ev["claim_keys"],
                    round_num=ev["round_num"],
                    profile_id=profile_id,
                    actor_user_id=actor_user_id,
                    run_id=run_id,
                    panel_id=self.panel_id,
                )
            except Exception as err:
                logger.warning("Failed to record cross-read audit event: %s", err)

        return scoped_proposals

    def to_state_dict(self) -> Dict[str, Any]:
        """Serializes blackboard state for the AgentState['deliberation_state'] channel."""
        d: Dict[str, Any] = {
            "panel_id": self.panel_id,
            "shared_constraints": [c.model_dump() for c in self.shared_constraints],
            "proposals": {
                r: {aid: p.model_dump() for aid, p in props.items()}
                for r, props in self.proposals.items()
            },
            "critiques": {
                r: [c.model_dump() for c in crits]
                for r, crits in self.critiques.items()
            },
            "active_proposals": {
                aid: p.model_dump() for aid, p in self.active_proposals.items()
            },
            "staged_actions": [a.model_dump() for a in self.get_active_staged_actions()],
            "missing_agents": list(self.missing_agents),
            "recorded_cross_reads": list(self.recorded_cross_reads),
        }
        if self.degraded:
            d["degraded"] = True
        return d

    @classmethod
    def from_state_dict(cls, data: Optional[Dict[str, Any]]) -> BlackboardManager:
        """Hydrates BlackboardManager from AgentState['deliberation_state']."""
        if not data:
            return cls()
        bb = cls(
            panel_id=data.get("panel_id"),
            shared_constraints=[
                SharedConstraint.model_validate(c)
                for c in data.get("shared_constraints", [])
            ],
        )
        for r_str, props in data.get("proposals", {}).items():
            r = int(r_str)
            bb.proposals[r] = {
                aid: AgentProposal.model_validate(p) for aid, p in props.items()
            }
        for r_str, crits in data.get("critiques", {}).items():
            r = int(r_str)
            bb.critiques[r] = [PeerCritique.model_validate(c) for c in crits]
        bb.active_proposals = {
            aid: AgentProposal.model_validate(p)
            for aid, p in data.get("active_proposals", {}).items()
        }
        bb.missing_agents = list(data.get("missing_agents", []))
        bb.degraded = bool(data.get("degraded", False))
        bb.recorded_cross_reads = list(data.get("recorded_cross_reads", []))
        return bb


# Public alias
DeliberationBlackboard = BlackboardManager
