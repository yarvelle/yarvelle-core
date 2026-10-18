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


def collect_routing_hints(packs: Sequence[PackSpec]) -> List[RoutingHints]:
    """Extracts and normalizes RoutingHints from a collection of active packs."""
    hints: List[RoutingHints] = []
    for pack in packs:
        if pack.routing_hints is not None:
            hints.append(pack.routing_hints)
        else:
            # Generate fallback hints from pack metadata
            hints.append(
                RoutingHints(
                    domain=pack.domain,
                    description=pack.description or f"Requests pertaining to {pack.name} ({pack.domain}).",
                    default_agent=f"{pack.domain}-guide",
                    domains_info={"categories": f"{pack.domain}.general"},
                )
            )
    return hints


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
