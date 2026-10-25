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

"""Disagree-or-Commit peer critique matrix for multi-agent deliberation.

Enforces ADR 0001 §2.2 & §2.8:
- Disagree-or-Commit stances: ENDORSE, COMPLEMENT, AMEND, CONFLICT.
- Bare agreement boilerplate (e.g. "lgtm", "agree", "+1") is rejected;
  ENDORSE requires substantive supporting rationale.
- Self-critiques (reviewer == target) are strictly rejected.
- Supports both per_agent (isolated calls per reviewer) and batched
  (single structured matrix call) modes.
- At most 1 schema repair retry per validation failure.
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.schemas.plan import SharedConstraint
from yarvelle_core.scope.context import ScopeContext, scope_context
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager, is_same_domain
from yarvelle_core.workflows.state import AgentProposal, PeerCritique

logger = logging.getLogger(__name__)


def parse_json_or_literal(raw: Union[str, Any]) -> Any:
    """Parses raw text, LangChain AIMessage, or Python literal into structured dict/list."""
    if isinstance(raw, (dict, list)):
        return raw
    if hasattr(raw, "content"):
        raw = raw.content
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()

    # Robust regex extraction of markdown code blocks anywhere in text
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        content_to_parse = match.group(1).strip()
    else:
        content_to_parse = raw

    try:
        return json.loads(content_to_parse)
    except Exception:
        try:
            return ast.literal_eval(content_to_parse)
        except Exception:
            if match and content_to_parse != raw:
                try:
                    return json.loads(raw)
                except Exception:
                    try:
                        return ast.literal_eval(raw)
                    except Exception:
                        pass
            raise ValueError(f"Failed to parse critique payload as JSON or literal: {raw}")


async def _invoke_model_async(model: BaseChatModel, messages: List[Any]) -> Any:
    """Invokes chat model asynchronously or via executor if synchronous."""
    if hasattr(model, "ainvoke"):
        return await model.ainvoke(messages)
    loop = None
    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    if loop is not None:
        return await loop.run_in_executor(None, model.invoke, messages)
    return model.invoke(messages)


async def run_peer_critiques(
    proposals: Union[Sequence[AgentProposal], Dict[str, AgentProposal]],
    mode: Literal["per_agent", "batched"] = "per_agent",
    model: Optional[BaseChatModel] = None,
    round_num: int = 1,
    shared_constraints: Optional[Sequence[SharedConstraint]] = None,
    max_retries: int = 1,
    blackboard: Optional[BlackboardManager] = None,
    context: Optional[Dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
    session_factory: Optional[Any] = None,
) -> List[PeerCritique]:
    """Executes peer review across specialist proposals using Disagree-or-Commit protocol.

    Args:
        proposals: Active proposals to review.
        mode: 'per_agent' (individual calls per reviewer) or 'batched' (single matrix call).
        model: Chat model used to generate critiques.
        round_num: Current deliberation round number.
        shared_constraints: Optional list of shared resource constraints.
        max_retries: Maximum schema repair retries (default 1).
        blackboard: Optional blackboard manager instance.
        context: Optional execution context dictionary (e.g. AgentState).
        session: Optional SQLAlchemy AsyncSession for DB audit logging.
        session_factory: Optional session factory for DB audit logging.

    Returns:
        List of validated PeerCritique models.
    """
    if isinstance(proposals, dict):
        prop_list = list(proposals.values())
    else:
        prop_list = list(proposals)

    if len(prop_list) < 2 or model is None:
        return []

    bb = blackboard
    if bb is None:
        bb = BlackboardManager()
        for p in prop_list:
            bb.record_proposal(p)

    critiques: List[PeerCritique] = []

    if mode == "batched":
        # Batched mode: single model call producing pairwise critique matrix
        # Fail closed on empty/mixed/unscoped panels: panel is same-domain ONLY if all scopes exist, are non-empty, and share domain
        cleaned_scopes = [(p.scope or "").strip() for p in prop_list]
        domain_prefixes = [s.split(".")[0] for s in cleaned_scopes]
        all_scopes_valid = all(
            bool(s) and bool(p) and "/" not in p and "\\" not in p
            for s, p in zip(cleaned_scopes, domain_prefixes)
        )
        is_same_panel = (
            all_scopes_valid
            and len(set(domain_prefixes)) == 1
            and all(is_same_domain(cleaned_scopes[0], s) for s in cleaned_scopes[1:])
        )
        is_cross_domain = not is_same_panel
        system_prompt = (
            "You are a deliberation moderator analyzing specialist proposals using "
            "the Disagree-or-Commit peer review protocol.\n"
            "Generate a JSON array of PeerCritique objects reviewing all peer interactions.\n"
            "Requirements:\n"
            "- Stances: 'endorse', 'complement', 'amend', 'conflict'.\n"
            "- Issue types: 'resource_overbudget', 'contraindication', 'dependency_order', 'synergy', 'risk_exposure'.\n"
            "- reviewer_agent_id and target_agent_id must be different (no self-critique).\n"
            "- If stance is 'endorse', critique MUST contain substantive supporting rationale (no bare agreement).\n"
            "- If stance is 'amend' or 'conflict', critique and proposed_resolution MUST be non-empty."
        )
        if is_cross_domain:
            system_prompt += (
                "\n- Cross-domain interactions may reference ONLY exported typed claims and shared constraints. "
                "Free-text summaries and recommendations are withheld across domain boundaries."
            )

        formatted_props = []
        for p in prop_list:
            if not is_cross_domain:
                formatted_props.append(
                    f"Agent: {p.agent_id}\nScope: {p.scope}\nSummary: {p.summary}\nClaims: {p.resource_claims}"
                )
            else:
                claim_bullets = "\n".join(
                    f"  - [{c.kind}] {c.key}: {c.value} {c.unit or ''}".strip()
                    for c in p.exported_claims
                ) or "  (No exported claims)"
                formatted_props.append(
                    f"Agent: {p.agent_id} (Cross-Domain)\nScope: {p.scope}\n[Summary withheld across domain boundaries]\nExported Claims:\n{claim_bullets}"
                )
        proposals_summary = "\n\n".join(formatted_props)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=f"Deliberation Round {round_num} proposals:\n{proposals_summary}\n\nProduce critique matrix JSON:"
            ),
        ]

        ctx = dict(context or {})
        moderator_scope = ctx.get("scope", "moderator")
        moderator_actor = ctx.get("moderator_id", "deliberation_moderator")
        if moderator_scope:
            mod_grants = ctx.get("granted_scopes")
            effective_mod_grants = (
                set(mod_grants) | {moderator_scope, f"{moderator_scope}.*"}
            ) if mod_grants is not None else None
            mod_scope_mgr = scope_context(
                scope=moderator_scope,
                profile_id=ctx.get("profile_id"),
                actor=moderator_actor,
                pack_id=ctx.get("pack_id"),
                granted_scopes=effective_mod_grants,
                pack_declared_scopes=ctx.get("pack_declared_scopes"),
                declared_reads=ctx.get("declared_reads"),
            )
        else:
            mod_scope_mgr = contextlib.nullcontext()

        with mod_scope_mgr:
            attempt = 0
            while attempt <= max_retries:
                attempt += 1
                raw_response = await _invoke_model_async(model, messages)
                try:
                    parsed = parse_json_or_literal(raw_response)
                    items = parsed if isinstance(parsed, list) else [parsed]
                    batch_critiques = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item["round_num"] = round_num
                        # Filter self-critique
                        if item.get("reviewer_agent_id") == item.get("target_agent_id"):
                            continue
                        critique_obj = PeerCritique.model_validate(item)
                        batch_critiques.append(critique_obj)
                    critiques.extend(batch_critiques)
                    break
                except (ValidationError, ValueError, json.JSONDecodeError) as err:
                    logger.warning(
                        "Batched critique schema validation failed on attempt %d: %s",
                        attempt,
                        err,
                    )
                    if attempt <= max_retries:
                        messages.append(
                            HumanMessage(
                                content=(
                                    f"The previous output failed validation: {err}. "
                                    "Please return a valid JSON array of PeerCritique objects."
                                )
                            )
                        )
                    else:
                        logger.error("Batched critique schema validation exhausted retries.")

    else:
        # per_agent mode: each reviewer independently critiques peer proposals
        ctx = dict(context or {})
        ambient = ScopeContext.get()

        for reviewer in prop_list:
            rev_scope = reviewer.scope or (ctx.get("agent_scopes", {}).get(reviewer.agent_id) if ctx else "")

            # Resolve declared_reads and granted_scopes for this reviewer
            agent_declared = ctx.get("agent_declared_reads", {})
            if isinstance(agent_declared, dict) and reviewer.agent_id in agent_declared:
                rev_declared_reads = agent_declared[reviewer.agent_id]
            elif "declared_reads" in ctx:
                rev_declared_reads = ctx["declared_reads"]
            elif ambient and ambient.declared_reads:
                rev_declared_reads = ambient.declared_reads
            else:
                rev_declared_reads = None

            agent_granted = ctx.get("agent_granted_scopes", {})
            if isinstance(agent_granted, dict) and reviewer.agent_id in agent_granted:
                rev_granted_scopes = agent_granted[reviewer.agent_id]
            elif "granted_scopes" in ctx:
                rev_granted_scopes = ctx["granted_scopes"]
            elif ambient and ambient.granted_scopes:
                rev_granted_scopes = ambient.granted_scopes
            else:
                rev_granted_scopes = None

            if rev_scope:
                effective_grants = (
                    set(rev_granted_scopes) | {rev_scope, f"{rev_scope}.*"}
                ) if rev_granted_scopes is not None else None
                scope_mgr = scope_context(
                    scope=rev_scope,
                    profile_id=ctx.get("profile_id"),
                    actor=reviewer.agent_id,
                    pack_id=ctx.get("pack_id"),
                    granted_scopes=effective_grants,
                    pack_declared_scopes=ctx.get("pack_declared_scopes"),
                    declared_reads=rev_declared_reads,
                )
            else:
                scope_mgr = contextlib.nullcontext()

            with scope_mgr:
                scoped_peer_map = await bb.get_scoped_proposals_for(
                    reader_agent_id=reviewer.agent_id,
                    reader_scope=rev_scope,
                    declared_reads=rev_declared_reads,
                    granted_scopes=rev_granted_scopes,
                    round_num=round_num,
                    session=session,
                    session_factory=session_factory,
                    profile_id=ctx.get("profile_id"),
                    actor_user_id=ctx.get("user_id") or ctx.get("actor_user_id"),
                    run_id=ctx.get("run_id"),
                )
                peers = list(scoped_peer_map.values())
                if not peers:
                    continue

                system_prompt = (
                    f"You are specialist agent '{reviewer.agent_id}' conducting peer review in Round {round_num}.\n"
                    "Evaluate peer proposals under Disagree-or-Commit:\n"
                    "- Stances: 'endorse', 'complement', 'amend', 'conflict'.\n"
                    "- Issue types: 'resource_overbudget', 'contraindication', 'dependency_order', 'synergy', 'risk_exposure'.\n"
                    "- Endorsements require substantive supporting points (bare 'agree' is rejected).\n"
                    "- Amendments/Conflicts require non-empty critique and proposed_resolution.\n"
                    "- When reviewing cross-domain peers, critique ONLY exported typed claims and shared constraints; "
                    "free-text proposals and recommendations are withheld across domain boundaries (ADR 0001 §2.3).\n"
                    "Output a JSON array of PeerCritique objects."
                )
                formatted_peer_blocks = []
                for p in peers:
                    if rev_scope and is_same_domain(rev_scope, p.scope):
                        recs_str = f"\nRecommendations: {', '.join(p.recommendations)}" if p.recommendations else ""
                        formatted_peer_blocks.append(
                            f"Peer Agent: {p.agent_id} (Same Domain)\n"
                            f"Scope: {p.scope}\n"
                            f"Summary: {p.summary}{recs_str}\n"
                            f"Claims: {p.resource_claims}"
                        )
                    else:
                        claim_lines = []
                        for c in p.exported_claims:
                            if c.key == "undisclosed_constraint":
                                claim_lines.append(f"  - [withheld] Undisclosed constraint exists on scope '{c.source_scope}'")
                            else:
                                unit_str = f" {c.unit}" if c.unit else ""
                                claim_lines.append(f"  - [{c.kind}] {c.key}: {c.value}{unit_str}")
                        claim_bullets = "\n".join(claim_lines) if claim_lines else "  (No exported claims)"
                        formatted_peer_blocks.append(
                            f"Peer Agent: {p.agent_id} (Cross-Domain)\n"
                            f"Scope: {p.scope}\n"
                            f"[Notice: Free-text proposal summary and recommendations are withheld across domain boundaries]\n"
                            f"Exported Typed Claims:\n{claim_bullets}"
                        )

                peers_summary = "\n\n".join(formatted_peer_blocks)
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content=(
                            f"Your own proposal summary: {reviewer.summary}\n\n"
                            f"Peer proposals:\n{peers_summary}\n\n"
                            "Provide your peer critiques as a JSON array:"
                        )
                    ),
                ]

                attempt = 0
                while attempt <= max_retries:
                    attempt += 1
                    raw_response = await _invoke_model_async(model, messages)
                    try:
                        parsed = parse_json_or_literal(raw_response)
                        items = parsed if isinstance(parsed, list) else [parsed]
                        agent_critiques = []
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            item["reviewer_agent_id"] = reviewer.agent_id
                            item["round_num"] = round_num
                            if item.get("reviewer_agent_id") == item.get("target_agent_id"):
                                continue
                            critique_obj = PeerCritique.model_validate(item)
                            agent_critiques.append(critique_obj)
                        critiques.extend(agent_critiques)
                        break
                    except (ValidationError, ValueError, json.JSONDecodeError) as err:
                        logger.warning(
                            "Agent '%s' peer critique failed validation on attempt %d: %s",
                            reviewer.agent_id,
                            attempt,
                            err,
                        )
                        if attempt <= max_retries:
                            messages.append(
                                HumanMessage(
                                    content=(
                                        f"The previous output failed validation: {err}. "
                                        "Please return a valid JSON array of PeerCritique objects."
                                    )
                                )
                            )
                        else:
                            logger.error(
                                "Agent '%s' peer critique failed after retry; skipping agent's critique.",
                                reviewer.agent_id,
                            )

    return critiques
