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

"""Blackboard deliberation engine runtime coordinator.

Enforces ADR 0001 §2 & §7 Phase 1:
- Bounded cyclic loop: Propose -> CrossExamine -> ConvergenceGate -> SelectiveRevise -> Synthesize.
- Read-only tools during deliberation; staged actions dropped in Phase 1.
- Deterministic budget auditor + Disagree-or-Commit peer critiques.
- Rule-based convergence ignoring self-reported confidence.
- Selective revision re-running ONLY targeted specialists.
- Fault tolerance: 1 schema repair retry, single-agent fallback if < 2 proposals survive.
- Deliberation SSE event emission.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.constants.api import (
    SSE_EVENT_DELIBERATION_CRITIQUE,
    SSE_EVENT_DELIBERATION_END,
    SSE_EVENT_DELIBERATION_PROPOSAL,
    SSE_EVENT_DELIBERATION_REVISION,
    SSE_EVENT_PANEL_START,
)
from yarvelle_core.schemas.plan import DeliberationConfig
from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.gate import evaluate_convergence_gate
from yarvelle_core.workflows.deliberation.propose import run_propose_phase
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.state import AgentProposal, AgentState, CritiqueStance, PeerCritique

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks.manager import adispatch_custom_event
except ImportError:
    adispatch_custom_event = None


async def _emit_sse_event(name: str, data: Dict[str, Any]) -> None:
    """Emits an SSE streaming custom event if event dispatcher is active."""
    if adispatch_custom_event is not None:
        try:
            payload = {"type": name, **data} if "type" not in data else data
            await adispatch_custom_event(name, payload)
        except Exception as err:
            logger.debug("Custom event '%s' emission skipped: %s", name, err)


class BudgetDecision(NamedTuple):
    """Result of budget check evaluation."""

    exhausted: bool
    reason: str


class DeliberationEngine:
    """Multi-agent blackboard deliberation engine coordinating bounded deliberation."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        registry: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        default_tools: Optional[Sequence[Any]] = None,
        config: Optional[DeliberationConfig] = None,
        session: Optional[AsyncSession] = None,
        session_factory: Optional[Any] = None,
    ) -> None:
        self.model = model
        self.registry = registry
        self.tool_registry = tool_registry
        self.default_tools = list(default_tools) if default_tools is not None else None
        self.config = config or DeliberationConfig()
        self.session = session
        self.session_factory = session_factory
        self._start_time: float = 0.0

    def check_budget(self, round_num: int, total_tokens: int = 0) -> BudgetDecision:
        """Evaluates wall-clock, token, and round limits against the budget."""
        budget = self.config.budget

        # 1. Wall-clock limit
        if self._start_time > 0:
            elapsed = time.time() - self._start_time
            if elapsed >= budget.max_wall_clock_s:
                return BudgetDecision(exhausted=True, reason="wall_clock_timeout")

        # 2. Token budget
        if total_tokens > 0 and total_tokens >= budget.max_total_tokens:
            return BudgetDecision(exhausted=True, reason="token_budget_exhausted")

        # 3. Maximum rounds
        if round_num > budget.max_rounds:
            return BudgetDecision(exhausted=True, reason="max_rounds_reached")

        return BudgetDecision(exhausted=False, reason="within_budget")

    async def run(self, state: AgentState) -> AgentState:
        """Runs the bounded blackboard deliberation lifecycle.

        Phase 1 Steps:
        1. Initialize blackboard and emit panel_start.
        2. Round 1: Propose (all specialists in read-only mode).
           Verify >= 2 proposals survive, else degrade to single-agent fallback.
        3. CrossExamine: Deterministic constraint auditor + DoC peer critiques.
        4. ConvergenceGate: Check consensus / max_rounds / budgets.
        5. Round 2+: SelectiveRevise for challenged agents only.
        6. Advance to Synthesize and emit deliberation_end.
        """
        self._start_time = time.time()
        total_tokens = 0

        # Resolve plan and active configuration
        plan = state.get("execution_plan")
        if plan is not None:
            plan_cfg = (
                getattr(plan, "deliberation_config", None)
                or (plan.get("deliberation_config") if isinstance(plan, dict) else None)
            )
            if plan_cfg is not None:
                if isinstance(plan_cfg, DeliberationConfig):
                    self.config = plan_cfg
                elif isinstance(plan_cfg, dict):
                    self.config = DeliberationConfig.model_validate(plan_cfg)

        target_agents: List[str] = []
        if plan is not None:
            raw_targets = getattr(plan, "target_agents", None) or (
                plan.get("target_agents") if isinstance(plan, dict) else None
            )
            if raw_targets:
                target_agents = list(raw_targets)

        if not target_agents and state.get("target_agents"):
            target_agents = list(state["target_agents"])

        if not target_agents:
            cur = state.get("current_agent") or state.get("agent_id")
            if cur:
                target_agents = [str(cur)]

        bb = BlackboardManager(
            panel_id=self.config.panel_id,
            shared_constraints=self.config.shared_constraints,
        )

        # Collect panel scopes
        panel_scopes: List[str] = []
        if plan is not None:
            raw_scopes = getattr(plan, "scopes", None) or (
                plan.get("scopes") if isinstance(plan, dict) else None
            )
            if raw_scopes:
                panel_scopes = list(raw_scopes)
        if not panel_scopes and self.config:
            raw_scopes = getattr(self.config, "scopes", None)
            if raw_scopes:
                panel_scopes = list(raw_scopes)
        if not panel_scopes and state.get("scopes"):
            panel_scopes = list(state["scopes"])
        if not panel_scopes and state.get("agent_scopes"):
            agent_sc_map = state.get("agent_scopes") or {}
            panel_scopes = list({agent_sc_map[a] for a in target_agents if a in agent_sc_map})
        if not panel_scopes and state.get("scope"):
            panel_scopes = [state["scope"]]

        # Emit panel_start event
        await _emit_sse_event(
            SSE_EVENT_PANEL_START,
            {
                "panel_id": self.config.panel_id,
                "title": getattr(plan, "title", "Panel Deliberation") if plan else "Panel Deliberation",
                "agents": list(target_agents),
                "shared_constraints": [c.model_dump() for c in self.config.shared_constraints],
                "scopes": list(panel_scopes),
            },
        )

        round_num = 1
        rounds_used = 1
        converged = False
        termination_reason = "max_rounds"
        last_skipped_constraints: List[str] = []

        while round_num <= self.config.budget.max_rounds:
            rounds_used = round_num

            # Check budget
            budget_decision = self.check_budget(round_num, total_tokens)
            if budget_decision.exhausted:
                termination_reason = budget_decision.reason
                break

            # 1. Propose (Round 1) or SelectiveRevise (Round > 1)
            if round_num == 1:
                proposals, missing = await run_propose_phase(
                    active_agents=target_agents,
                    round_num=1,
                    context=dict(state),
                    model=self.model,
                    tools=self.default_tools,
                )
                for prop in proposals.values():
                    bb.record_proposal(prop)
                    await _emit_sse_event(
                        SSE_EVENT_DELIBERATION_PROPOSAL,
                        {
                            "round": 1,
                            "agent_id": prop.agent_id,
                            "scope": prop.scope,
                            "summary": prop.summary,
                            "resource_claims": prop.resource_claims,
                            "tainted": prop.tainted,
                        },
                    )
                bb.missing_agents.extend(missing)

                # Fault tolerance: check minimum panel size
                if len(proposals) < 2:
                    logger.warning(
                        "Deliberation panel degraded: fewer than 2 valid proposals survived (%d valid).",
                        len(proposals),
                    )
                    bb.degraded = True
                    delib_state = bb.to_state_dict()
                    delib_state["degraded"] = True
                    delib_state["rounds_used"] = 1
                    delib_state["termination_reason"] = "single_agent_fallback"
                    delib_state["skipped_constraints"] = []
                    state["deliberation_state"] = delib_state
                    state["specialist_outputs"] = {aid: p.summary for aid, p in proposals.items()}
                    single_summary = list(proposals.values())[0].summary if proposals else "No proposal available"
                    state["output"] = (
                        f"Deliberation degraded to single-agent answer due to missing peer perspectives. "
                        f"Missing agents: {missing}. Output: {single_summary}"
                    )
                    await _emit_sse_event(
                        SSE_EVENT_DELIBERATION_END,
                        {
                            "reason": "single_agent_fallback",
                            "rounds_used": 1,
                            "open_conflicts": 0,
                            "missing_agents": list(missing),
                        },
                    )
                    return state

            else:
                prior_round = round_num - 1
                prior_critiques = bb.critiques.get(prior_round, [])
                revised_proposals = await run_selective_revision(
                    active_proposals=bb.active_proposals,
                    critiques=prior_critiques,
                    round_num=round_num,
                    model=self.model,
                    context=dict(state),
                    shared_constraints=bb.shared_constraints,
                    tools=self.default_tools,
                )
                for prop in revised_proposals.values():
                    bb.record_proposal(prop)
                    if prop.round_num == round_num:
                        agent_resolved_critiques = [
                            f"{c.reviewer_agent_id}: {c.critique}"
                            for c in prior_critiques
                            if c.target_agent_id == prop.agent_id
                        ]
                        await _emit_sse_event(
                            SSE_EVENT_DELIBERATION_REVISION,
                            {
                                "round": round_num,
                                "agent_id": prop.agent_id,
                                "scope": prop.scope,
                                "summary": prop.summary,
                                "resolved_critiques": agent_resolved_critiques,
                            },
                        )

            # 2. CrossExamine Phase
            # 2a. Deterministic Budget Auditor
            auditor = BudgetAuditor()
            auditor_critiques = auditor.audit(
                constraints=bb.shared_constraints,
                proposals=bb.active_proposals,
                round_num=round_num,
                moderator_id=self.config.moderator_agent_id,
            )
            last_skipped_constraints = auditor.skipped_constraints

            # 2b. Peer Critiques (Disagree-or-Commit)
            effective_session = getattr(self, "session", None) or state.get("session") or state.get("db_session")
            effective_factory = getattr(self, "session_factory", None) or state.get("session_factory")

            peer_critiques = await run_peer_critiques(
                proposals=bb.active_proposals,
                mode=self.config.critique_mode,
                model=self.model,
                round_num=round_num,
                shared_constraints=bb.shared_constraints,
                blackboard=bb,
                context=dict(state),
                session=effective_session,
                session_factory=effective_factory,
            )

            all_critiques = auditor_critiques + peer_critiques
            for c in all_critiques:
                rev_prop = bb.active_proposals.get(c.reviewer_agent_id)
                tgt_prop = bb.active_proposals.get(c.target_agent_id)
                reviewer_scope = getattr(rev_prop, "scope", "") if rev_prop else ""
                target_scope = getattr(tgt_prop, "scope", "") if tgt_prop else ""
                await _emit_sse_event(
                    SSE_EVENT_DELIBERATION_CRITIQUE,
                    {
                        "round": round_num,
                        "reviewer_id": c.reviewer_agent_id,
                        "target_id": c.target_agent_id,
                        "reviewer_scope": reviewer_scope,
                        "target_scope": target_scope,
                        "stance": c.stance.value,
                        "issue_type": c.issue_type,
                        "critique": c.critique,
                    },
                )
            bb.record_critiques(round_num, all_critiques)

            # 3. ConvergenceGate
            gate_decision = evaluate_convergence_gate(
                critiques=all_critiques,
                round_num=round_num,
                max_rounds=self.config.budget.max_rounds,
                budget=self.config.budget,
                start_time=self._start_time,
                total_tokens=total_tokens,
                active_agents=list(bb.active_proposals.keys()),
            )

            if gate_decision.next_node == "synthesize":
                converged = gate_decision.converged
                termination_reason = gate_decision.reason
                break
            else:
                round_num += 1

        # Finalize deliberation state
        delib_state = bb.to_state_dict()
        delib_state["rounds_used"] = rounds_used
        delib_state["converged"] = converged
        delib_state["termination_reason"] = termination_reason
        delib_state["degraded"] = False
        delib_state["skipped_constraints"] = last_skipped_constraints

        state["deliberation_state"] = delib_state
        state["specialist_outputs"] = {aid: p.summary for aid, p in bb.active_proposals.items()}

        # Forward cross-read audit events to state
        if "audit_events" in state or bb.recorded_cross_reads:
            state_audit_events = list(state.get("audit_events") or [])
            for cr in bb.recorded_cross_reads:
                event_dict = {
                    "event": "scope.cross_read",
                    "reader_agent_id": cr.get("reader_agent_id"),
                    "reader_scope": cr.get("reader_scope"),
                    "target_agent_id": cr.get("target_agent_id"),
                    "target_scope": cr.get("target_scope"),
                    "claim_keys": cr.get("claim_keys"),
                    "round_num": cr.get("round_num"),
                    "panel_id": bb.panel_id,
                }
                if event_dict not in state_audit_events:
                    state_audit_events.append(event_dict)
            state["audit_events"] = state_audit_events

        if not state.get("output"):
            summaries = [f"### {aid}\n{p.summary}" for aid, p in bb.active_proposals.items()]
            state["output"] = "\n\n".join(summaries)

        open_conflicts = sum(
            1 for c in bb.critiques.get(rounds_used, [])
            if not c.resolved and c.stance == CritiqueStance.CONFLICT
        )
        await _emit_sse_event(
            SSE_EVENT_DELIBERATION_END,
            {
                "reason": termination_reason,
                "rounds_used": rounds_used,
                "open_conflicts": open_conflicts,
                "missing_agents": bb.missing_agents,
            },
        )

        return state
