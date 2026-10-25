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
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from yarvelle_core.schemas.plan import SharedConstraint
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
) -> List[PeerCritique]:
    """Executes peer review across specialist proposals using Disagree-or-Commit protocol.

    Args:
        proposals: Active proposals to review.
        mode: 'per_agent' (individual calls per reviewer) or 'batched' (single matrix call).
        model: Chat model used to generate critiques.
        round_num: Current deliberation round number.
        shared_constraints: Optional list of shared resource constraints.
        max_retries: Maximum schema repair retries (default 1).

    Returns:
        List of validated PeerCritique models.
    """
    if isinstance(proposals, dict):
        prop_list = list(proposals.values())
    else:
        prop_list = list(proposals)

    if len(prop_list) < 2 or model is None:
        return []

    critiques: List[PeerCritique] = []

    if mode == "batched":
        # Batched mode: single model call producing pairwise critique matrix
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
        proposals_summary = "\n\n".join(
            f"Agent: {p.agent_id}\nScope: {p.scope}\nSummary: {p.summary}\nClaims: {p.resource_claims}"
            for p in prop_list
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=f"Deliberation Round {round_num} proposals:\n{proposals_summary}\n\nProduce critique matrix JSON:"
            ),
        ]

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
        for reviewer in prop_list:
            peers = [p for p in prop_list if p.agent_id != reviewer.agent_id]
            if not peers:
                continue

            system_prompt = (
                f"You are specialist agent '{reviewer.agent_id}' conducting peer review in Round {round_num}.\n"
                "Evaluate peer proposals under Disagree-or-Commit:\n"
                "- Stances: 'endorse', 'complement', 'amend', 'conflict'.\n"
                "- Issue types: 'resource_overbudget', 'contraindication', 'dependency_order', 'synergy', 'risk_exposure'.\n"
                "- Endorsements require substantive supporting points (bare 'agree' is rejected).\n"
                "- Amendments/Conflicts require non-empty critique and proposed_resolution.\n"
                "Output a JSON array of PeerCritique objects."
            )
            peers_summary = "\n\n".join(
                f"Peer Agent: {p.agent_id}\nScope: {p.scope}\nSummary: {p.summary}\nClaims: {p.resource_claims}"
                for p in peers
            )
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
