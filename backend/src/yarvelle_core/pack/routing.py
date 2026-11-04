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

"""Dynamic orchestrator routing hint composition from registered packs."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence
from yarvelle_core.pack.spec import PackSpec
from yarvelle_core.schemas.routing import RoutingHints


def _pack_default_agent(pack: PackSpec) -> Optional[str]:
    """Returns the pack's configured ``orchestration.default_agent``, if any."""
    orchestration = getattr(pack, "orchestration", None)
    agent_id = getattr(orchestration, "default_agent", None) if orchestration is not None else None
    agent_id = (agent_id or "").strip()
    return agent_id or None


def collect_routing_hints(packs: Sequence[PackSpec]) -> List[RoutingHints]:
    """Extracts and normalizes RoutingHints from a collection of active packs.

    A pack contributes its explicit ``routing_hints`` when present. Otherwise
    hints are built from pack metadata only when the pack names an
    ``orchestration.default_agent``; core never invents an agent id, so a pack
    with neither is left out of domain routing.
    """
    hints: List[RoutingHints] = []
    for pack in packs:
        if pack.routing_hints is not None:
            hints.append(pack.routing_hints)
            continue
        default_agent = _pack_default_agent(pack)
        if default_agent is None:
            continue
        hints.append(
            RoutingHints(
                domain=pack.domain,
                description=pack.description or f"Requests pertaining to {pack.name} ({pack.domain}).",
                default_agent=default_agent,
                domains_info={"categories": f"{pack.domain}.general"},
            )
        )
    return hints


def resolve_default_agent(packs: Sequence[PackSpec]) -> Optional[str]:
    """Returns the single default agent configured across packs, or ``None``.

    Raises:
        ValueError: if two packs configure different default agents.
    """
    found: Dict[str, str] = {}
    for pack in packs:
        agent_id = _pack_default_agent(pack)
        if agent_id is not None:
            found[pack.id] = agent_id
    distinct = sorted(set(found.values()))
    if len(distinct) > 1:
        detail = ", ".join(f"{pid}={aid}" for pid, aid in sorted(found.items()))
        raise ValueError(f"Packs configure conflicting orchestration.default_agent values: {detail}")
    return distinct[0] if distinct else None


def compose_orchestrator_routing_prompt(
    hints: Sequence[RoutingHints],
    product_name: str = "Yarvelle",
) -> str:
    """Composes dynamic Tier-1 domain classification prompt from pack hints."""
    domains_quoted = ", ".join(f"'{h.domain}'" for h in hints)
    domain_sections = []

    for idx, h in enumerate(hints, 1):
        info_block = f"{idx}. '{h.domain}': {h.description}"
        if h.domains_info:
            cats = h.domains_info.get("example_categories") or h.domains_info.get("categories", "")
            if cats:
                info_block += f"\n   Example subcategories: {cats}"
        domain_sections.append(info_block)

    domains_text = "\n\n".join(domain_sections)

    return (
        f"You are the {product_name} Tier-1 Intent and Domain Classifier.\n"
        "Your objective is to analyze the user inquiry and conversation context, then classify it into "
        "exactly one primary domain and an appropriate dot-notated subcategory.\n\n"
        "## Supported Domains:\n"
        f"{domains_text}\n\n"
        "## Output Instructions:\n"
        f"- Set 'domain' to one of: {domains_quoted}.\n"
        "- Set 'category' to a dot-notated category matching the user's inquiry.\n"
        "- Set 'reasoning' to a concise rationale explaining why the query belongs in this domain and category.\n"
        "Never attempt to answer specialized queries directly; classify strictly for downstream specialist routing."
    )
