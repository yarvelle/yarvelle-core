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

"""Proposal generator for multi-agent deliberation rounds.

Enforces ADR 0001 §2.6, §2.7 & §7 Phase 1:
- Only read-tier tools are accessible during deliberation rounds.
- Dropping staged write actions in Phase 1 (proposal.staged_actions = []).
- Fault tolerance: at most 1 schema repair retry per specialist.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from yarvelle_core.workflows.deliberation.doc_critique import _invoke_model_async, parse_json_or_literal
from yarvelle_core.workflows.deliberation.tool_gate import filter_read_only_tools
from yarvelle_core.workflows.state import AgentProposal

logger = logging.getLogger(__name__)


async def generate_agent_proposal(
    agent_id: str,
    round_num: int = 1,
    context: Optional[Dict[str, Any]] = None,
    model: Optional[BaseChatModel] = None,
    scope: str = "default_scope",
    tools: Optional[Sequence[Any]] = None,
    max_retries: int = 1,
) -> AgentProposal:
    """Invokes a specialist agent to generate a structured proposal for the round.

    Invariants:
    1. Read-only tools only: any non-read tool is filtered out.
    2. Staged write actions are dropped in Phase 1 (staged_actions = []).
    3. At most 1 repair retry is attempted upon validation failure.
    """
    if model is None:
        raise ValueError("A valid BaseChatModel is required to generate proposals.")

    read_tools = filter_read_only_tools(tools or [])
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

    user_prompt = ctx.get("prompt") or ctx.get("task") or "Coordinate domain tasks."

    system_prompt = (
        f"You are specialist agent '{agent_id}' in deliberation round {round_num}.\n"
        "Generate a structured proposal adhering to the AgentProposal JSON schema:\n"
        "- agent_id: string\n"
        "- round_num: integer\n"
        "- scope: string\n"
        "- summary: string\n"
        "- recommendations: list of strings\n"
        "- resource_claims: dict mapping constraint slug to numeric float\n"
        "- resource_claim_units: dict mapping constraint slug to allowed unit string\n"
        "Read-only tools are available. Staged write actions are forbidden in Phase 1."
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Task Context: {user_prompt}\n\nProduce proposal JSON:"),
    ]

    attempt = 0
    last_error: Optional[Exception] = None

    while attempt <= max_retries:
        attempt += 1
        raw_response = await _invoke_model_async(bound_model, messages)
        try:
            parsed = parse_json_or_literal(raw_response)
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected JSON object for AgentProposal, got {type(parsed).__name__}")

            parsed["agent_id"] = agent_id
            parsed["round_num"] = round_num
            parsed.setdefault("scope", scope)

            proposal = AgentProposal.model_validate(parsed)

            # Phase 1 safety invariant: drop staged write actions
            if proposal.staged_actions:
                logger.info(
                    "Phase 1: Dropping %d staged actions from agent '%s'.",
                    len(proposal.staged_actions),
                    agent_id,
                )
                proposal.staged_actions = []

            return proposal

        except (ValidationError, ValueError) as err:
            last_error = err
            logger.warning(
                "Agent '%s' proposal schema validation failed on attempt %d: %s",
                agent_id,
                attempt,
                err,
            )
            if attempt <= max_retries:
                messages.append(
                    HumanMessage(
                        content=(
                            f"The previous proposal was invalid: {err}. "
                            "Please provide a valid JSON object matching the AgentProposal schema."
                        )
                    )
                )

    raise ValueError(f"Agent '{agent_id}' failed schema validation after {attempt} attempt(s): {last_error}")


async def run_propose_phase(
    active_agents: Sequence[str],
    round_num: int,
    context: Optional[Dict[str, Any]] = None,
    model: Optional[BaseChatModel] = None,
    tools: Optional[Sequence[Any]] = None,
    max_retries: int = 1,
) -> Tuple[Dict[str, AgentProposal], List[str]]:
    """Runs Round 1 proposal generation across all active agents.

    Returns:
        Tuple of (valid_proposals_dict, failed_agent_ids).
    """
    proposals: Dict[str, AgentProposal] = {}
    missing_agents: List[str] = []

    for aid in active_agents:
        try:
            prop = await generate_agent_proposal(
                agent_id=aid,
                round_num=round_num,
                context=context,
                model=model,
                tools=tools,
                max_retries=max_retries,
            )
            proposals[aid] = prop
        except Exception as exc:
            logger.error("Agent '%s' dropped after failing proposal generation: %s", aid, exc)
            missing_agents.append(aid)

    return proposals, missing_agents
