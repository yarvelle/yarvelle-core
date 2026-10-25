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
from typing import Any, Dict, List, Optional

from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.workflows.state import AgentProposal, PeerCritique, StagedAction

logger = logging.getLogger(__name__)


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

    def record_proposal(self, proposal: AgentProposal) -> None:
        """Stores a proposal for its round and updates active_proposals.

        Phase 1 safety invariant: drops staged write actions.
        """
        if proposal.staged_actions:
            logger.info(
                "Phase 1 Deliberation: Dropping %d staged action(s) from agent '%s'.",
                len(proposal.staged_actions),
                proposal.agent_id,
            )
            proposal.staged_actions = []

        r = proposal.round_num
        if r not in self.proposals:
            self.proposals[r] = {}
        self.proposals[r][proposal.agent_id] = proposal
        self.active_proposals[proposal.agent_id] = proposal

    def get_active_staged_actions(self) -> List[StagedAction]:
        """Returns active staged actions (empty in Phase 1 per safety invariants)."""
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

    def get_scoped_proposals_for(
        self, reader_agent_id: str, reader_scope: str = ""
    ) -> Dict[str, AgentProposal]:
        """Returns peer proposals visible to the reader agent.

        In Phase 1 same-domain panels, all peer proposals are visible.
        """
        return {
            aid: p for aid, p in self.active_proposals.items()
            if aid != reader_agent_id
        }

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
            "missing_agents": list(self.missing_agents),
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
        return bb


# Public alias
DeliberationBlackboard = BlackboardManager
