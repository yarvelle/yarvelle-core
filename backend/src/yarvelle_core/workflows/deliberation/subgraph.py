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

"""LangGraph StateGraph builder for bounded multi-agent deliberation.

Constructs the cyclic state graph:
START -> Propose -> CrossExamine -> ConvergenceGate -> [SelectiveRevise -> CrossExamine | END]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from yarvelle_core.schemas.plan import DeliberationConfig
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.gate import evaluate_convergence_gate
from yarvelle_core.workflows.deliberation.propose import run_propose_phase
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.state import AgentProposal, AgentState, PeerCritique

logger = logging.getLogger(__name__)


def create_deliberation_subgraph(
    model: Optional[BaseChatModel] = None,
    registry: Optional[Any] = None,
    default_tools: Optional[Sequence[Any]] = None,
    config: Optional[DeliberationConfig] = None,
) -> StateGraph:
    """Builds a compiled LangGraph StateGraph for bounded multi-agent deliberation."""
    cfg = config or DeliberationConfig()

    async def propose_node(state: AgentState) -> Dict[str, Any]:
        """Runs initial proposals across active panel agents."""
        plan = state.get("execution_plan") or {}
        target_agents = (
            getattr(plan, "target_agents", None)
            or (plan.get("target_agents") if isinstance(plan, dict) else None)
            or state.get("target_agents")
            or []
        )
        shared_constraints = cfg.shared_constraints

        bb = BlackboardManager(
            panel_id=cfg.panel_id,
            shared_constraints=shared_constraints,
        )

        proposals, missing = await run_propose_phase(
            active_agents=target_agents,
            round_num=1,
            context=dict(state),
            model=model,
            tools=default_tools,
        )

        for prop in proposals.values():
            bb.record_proposal(prop)
        bb.missing_agents.extend(missing)

        d_state = bb.to_state_dict()
        d_state["round_num"] = 1
        d_state["rounds_used"] = 1

        if len(proposals) < 2:
            bb.degraded = True
            d_state["degraded"] = True
            d_state["next_step"] = "synthesize"
            output_msg = (
                f"Deliberation degraded to single-agent fallback because fewer than 2 valid proposals survived. "
                f"Missing agents: {missing}."
            )
            return {
                "deliberation_state": d_state,
                "specialist_outputs": {aid: p.summary for aid, p in proposals.items()},
                "output": output_msg,
            }

        return {
            "deliberation_state": d_state,
            "specialist_outputs": {aid: p.summary for aid, p in proposals.items()},
        }

    async def cross_examine_node(state: AgentState) -> Dict[str, Any]:
        """Executes constraint auditor and Disagree-or-Commit peer critiques."""
        d_state = dict(state.get("deliberation_state") or {})
        bb = BlackboardManager.from_state_dict(d_state)
        round_num = d_state.get("round_num", 1)

        # 1. Deterministic constraint budget auditor
        auditor = BudgetAuditor()
        auditor_critiques = auditor.audit(
            constraints=bb.shared_constraints,
            proposals=bb.active_proposals,
            round_num=round_num,
            moderator_id=cfg.moderator_agent_id,
        )
        d_state["skipped_constraints"] = auditor.skipped_constraints

        # 2. Peer critiques
        peer_critiques = await run_peer_critiques(
            proposals=bb.active_proposals,
            mode=cfg.critique_mode,
            model=model,
            round_num=round_num,
            shared_constraints=bb.shared_constraints,
        )

        all_critiques = auditor_critiques + peer_critiques
        bb.record_critiques(round_num, all_critiques)

        updated_d_state = bb.to_state_dict()
        for k in ("degraded", "termination_reason", "skipped_constraints"):
            if k in d_state and k not in updated_d_state:
                updated_d_state[k] = d_state[k]
        updated_d_state["round_num"] = round_num
        updated_d_state["rounds_used"] = round_num
        updated_d_state["skipped_constraints"] = auditor.skipped_constraints

        return {"deliberation_state": updated_d_state}

    def convergence_gate_node(state: AgentState) -> Dict[str, Any]:
        """Evaluates rule-based convergence gate."""
        d_state = dict(state.get("deliberation_state") or {})
        bb = BlackboardManager.from_state_dict(d_state)
        round_num = d_state.get("round_num", 1)
        round_critiques = bb.critiques.get(round_num, [])

        decision = evaluate_convergence_gate(
            critiques=round_critiques,
            round_num=round_num,
            max_rounds=cfg.budget.max_rounds,
            budget_remaining=True,
            budget=cfg.budget,
        )

        d_state["next_step"] = decision.next_node
        d_state["converged"] = decision.converged
        d_state["termination_reason"] = decision.reason
        d_state["targeted_agents"] = decision.target_agents

        return {"deliberation_state": d_state}

    async def selective_revise_node(state: AgentState) -> Dict[str, Any]:
        """Re-runs only targeted specialists, preserving untargeted proposals."""
        d_state = dict(state.get("deliberation_state") or {})
        bb = BlackboardManager.from_state_dict(d_state)
        prior_round = d_state.get("round_num", 1)
        new_round = prior_round + 1

        prior_critiques = bb.critiques.get(prior_round, [])

        revised_proposals = await run_selective_revision(
            active_proposals=bb.active_proposals,
            critiques=prior_critiques,
            round_num=new_round,
            model=model,
            context=dict(state),
            shared_constraints=bb.shared_constraints,
            tools=default_tools,
        )

        for prop in revised_proposals.values():
            bb.record_proposal(prop)

        updated_d_state = bb.to_state_dict()
        for k in ("degraded", "termination_reason", "skipped_constraints"):
            if k in d_state and k not in updated_d_state:
                updated_d_state[k] = d_state[k]
        updated_d_state["round_num"] = new_round
        updated_d_state["rounds_used"] = new_round

        return {
            "deliberation_state": updated_d_state,
            "specialist_outputs": {aid: p.summary for aid, p in revised_proposals.items()},
        }

    builder = StateGraph(AgentState)
    builder.add_node("propose", propose_node)
    builder.add_node("cross_examine", cross_examine_node)
    builder.add_node("convergence_gate", convergence_gate_node)
    builder.add_node("selective_revise", selective_revise_node)

    builder.add_edge(START, "propose")

    def route_propose(state: AgentState) -> str:
        d_state = state.get("deliberation_state") or {}
        if d_state.get("degraded") or len(d_state.get("active_proposals") or {}) < 2:
            return END
        return "cross_examine"

    builder.add_conditional_edges(
        "propose",
        route_propose,
        {"cross_examine": "cross_examine", END: END},
    )
    builder.add_edge("cross_examine", "convergence_gate")

    def route_gate(state: AgentState) -> str:
        d_state = state.get("deliberation_state") or {}
        if d_state.get("degraded"):
            return END
        if d_state.get("next_step") == "selective_revise":
            return "selective_revise"
        return END

    builder.add_conditional_edges(
        "convergence_gate",
        route_gate,
        {"selective_revise": "selective_revise", END: END},
    )
    builder.add_edge("selective_revise", "cross_examine")

    return builder
