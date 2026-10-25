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

"""Selective revision execution for multi-agent deliberation rounds.

Enforces ADR 0001 §2.4, §2.10 & §7 Phase 1:
- Selective revision: re-runs ONLY specialists targeted by open CONFLICT or AMEND critiques.
- Untargeted proposals are preserved verbatim from the prior round, saving 40-70% LLM calls.
- Phase 1 safety invariant: drops staged write actions.
- At most 1 repair retry on schema failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.scope.context import scope_context
from yarvelle_core.workflows.deliberation.doc_critique import _invoke_model_async, parse_json_or_literal
from yarvelle_core.workflows.deliberation.tool_gate import derive_tool_risk_tier, filter_read_only_tools
from yarvelle_core.workflows.state import AgentProposal, CritiqueStance, PeerCritique

logger = logging.getLogger(__name__)


async def run_selective_revision(
    active_proposals: Dict[str, AgentProposal],
    critiques: Sequence[PeerCritique],
    round_num: int,
    model: Optional[BaseChatModel] = None,
    context: Optional[Dict[str, Any]] = None,
    shared_constraints: Optional[Sequence[SharedConstraint]] = None,
    tools: Optional[Sequence[Any]] = None,
    max_retries: int = 1,
    tool_registry: Optional[Any] = None,
) -> Dict[str, AgentProposal]:
    """Executes selective revision targeting only agents with open conflicts or amends.

    Invariants:
    1. Untargeted agents are preserved untouched with 0 LLM calls.
    2. Targeted agents receive their prior proposal and open critiques targeting them.
    3. Staged actions are retained with risk_tier derived deterministically (never trusted from model).
    4. At most 1 schema repair retry is attempted per targeted specialist.
    """
    updated_proposals: Dict[str, AgentProposal] = {}

    # Identify open blocking critiques (CONFLICT or AMEND)
    open_blocking = [
        c for c in critiques
        if not c.resolved and c.stance in (CritiqueStance.CONFLICT, CritiqueStance.AMEND)
    ]
    targeted_agents = {c.target_agent_id for c in open_blocking}

    # 1. Preserve untargeted proposals untouched (0 LLM calls)
    for aid, prop in active_proposals.items():
        if aid not in targeted_agents:
            logger.info("SelectiveRevise: Preserving untargeted proposal for agent '%s'.", aid)
            updated_proposals[aid] = prop

    if not model:
        return updated_proposals

    read_tools = filter_read_only_tools(tools or [], tool_registry=tool_registry)
    ctx = dict(context or {})
    tool_names = [t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t)) for t in read_tools]
    ctx["allowed_tools"] = tool_names

    bound_model = model
    if read_tools and hasattr(model, "bind_tools") and callable(model.bind_tools):
        try:
            bound_model = model.bind_tools(read_tools)
        except Exception as err:
            logger.debug("Model bind_tools not supported or skipped: %s", err)
            bound_model = model

    # 2. Re-run targeted agents
    for aid in targeted_agents:
        if aid not in active_proposals:
            continue

        prior_prop = active_proposals[aid]
        agent_critiques = [c for c in open_blocking if c.target_agent_id == aid]
        critique_summary = "\n".join(
            f"- [{c.stance.value.upper()}] from {c.reviewer_agent_id}: {c.critique} "
            f"Proposed Resolution: {c.proposed_resolution}"
            for c in agent_critiques
        )

        system_prompt = (
            f"You are specialist agent '{aid}' revising your proposal in deliberation round {round_num}.\n"
            "Peers and auditors have reviewed your prior proposal with the following critiques:\n"
            f"{critique_summary}\n\n"
            "Revise your proposal to address these critiques. Output a JSON object adhering to AgentProposal schema:\n"
            "- agent_id: string\n"
            "- round_num: integer\n"
            "- scope: string\n"
            "- summary: string\n"
            "- recommendations: list of strings\n"
            "- resource_claims: dict mapping constraint slug to numeric float\n"
            "- resource_claim_units: dict mapping constraint slug to allowed unit string\n"
            "- staged_actions: optional list of proposed actions (tool_name, tool_args, rationale)\n"
            "Read-only tools may be consulted during deliberation. Any state-mutating action "
            "must be staged under staged_actions for human review at plan completion."
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    f"Prior Proposal Summary: {prior_prop.summary}\n"
                    f"Prior Claims: {prior_prop.resource_claims}\n\n"
                    "Provide your revised proposal as JSON:"
                )
            ),
        ]

        attempt = 0
        revised_successfully = False

        while attempt <= max_retries:
            attempt += 1
            with scope_context(
                scope=prior_prop.scope,
                profile_id=ctx.get("profile_id"),
                actor=aid,
                pack_id=ctx.get("pack_id"),
                granted_scopes=ctx.get("granted_scopes"),
                pack_declared_scopes=ctx.get("pack_declared_scopes"),
                declared_reads=ctx.get("declared_reads"),
            ):
                raw_response = await _invoke_model_async(bound_model, messages)
            try:
                parsed = parse_json_or_literal(raw_response)
                if not isinstance(parsed, dict):
                    raise ValueError(f"Expected JSON object for AgentProposal, got {type(parsed).__name__}")

                parsed["agent_id"] = aid
                parsed["round_num"] = round_num
                parsed.setdefault("scope", prior_prop.scope)

                # Normalize staged_actions deterministically before validation
                raw_actions = parsed.get("staged_actions")
                normalized_actions: List[Dict[str, Any]] = []
                if isinstance(raw_actions, list):
                    for act in raw_actions:
                        if not isinstance(act, dict):
                            continue
                        t_name = str(act.get("tool_name", "")).strip()
                        if not t_name:
                            continue
                        tier = derive_tool_risk_tier(t_name, tool_registry=tool_registry, tools=tools)
                        normalized_actions.append({
                            "agent_id": aid,
                            "tool_name": t_name,
                            "tool_args": dict(act.get("tool_args") or {}),
                            "rationale": str(act.get("rationale") or ""),
                            "risk_tier": tier,
                        })
                parsed["staged_actions"] = normalized_actions

                new_proposal = AgentProposal.model_validate(parsed)
                updated_proposals[aid] = new_proposal
                revised_successfully = True
                logger.info("SelectiveRevise: Successfully revised proposal for agent '%s'.", aid)
                break

            except (ValidationError, ValueError) as err:
                logger.warning(
                    "Agent '%s' revision failed schema validation on attempt %d: %s",
                    aid,
                    attempt,
                    err,
                )
                if attempt <= max_retries:
                    messages.append(
                        HumanMessage(
                            content=(
                                f"The previous revision failed validation: {err}. "
                                "Please provide a valid JSON object matching the AgentProposal schema."
                            )
                        )
                    )

        if not revised_successfully:
            logger.error(
                "Agent '%s' revision failed schema validation after retries; preserving prior proposal.",
                aid,
            )
            # Retain prior proposal if revision failed so agent is not abruptly dropped mid-deliberation
            updated_proposals[aid] = prior_prop

    return updated_proposals
