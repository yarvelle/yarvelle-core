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

"""Tool execution gating for multi-agent deliberation rounds.

Enforces ADR 0001 §2.6 and §7 Phase 1 safety invariants:
- Read-only tools only during deliberation rounds (Propose and SelectiveRevise).
- Write and irreversible operations are strictly blocked.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from yarvelle_core.engine.tool_exec import PolicyDecision, ToolContext, ToolSpec


def evaluate_deliberation_tool_gate(
    ctx: ToolContext,
    spec: Any,
    args: Dict[str, Any],
) -> PolicyDecision:
    """Evaluates tool execution policy during multi-agent deliberation rounds.

    Invariants:
    1. During deliberation rounds (Propose and SelectiveRevise), only read-tier tools are allowed.
    2. Any tool with a risk tier other than 'read' (e.g. write_local, write_external, irreversible)
       or missing/unknown risk_tier is strictly blocked (fail-closed).
    """
    if isinstance(spec, dict):
        raw_tier = spec.get("risk_tier")
        tool_name = spec.get("name", "unnamed")
    else:
        raw_tier = getattr(spec, "risk_tier", None)
        tool_name = getattr(spec, "name", "unnamed")

    tier = str(raw_tier).strip().lower() if raw_tier else None

    if tier == "read":
        return PolicyDecision.allow("Read operation permitted during deliberation rounds")

    return PolicyDecision.block(
        f"Non-read-tier tool '{tool_name}' with risk_tier '{tier}' is blocked "
        "during deliberation rounds. Only read-tier tools are permitted."
    )


def filter_read_only_tools(tools: Sequence[Any]) -> List[Any]:
    """Filters candidate tools to only those with risk_tier == 'read'.

    Invariants:
    1. Unknown tiers fail closed; never infer 'read' if missing or non-string.
    2. Supports both ToolSpec/object instances and dictionary tool definitions.
    3. Case-insensitive comparison against 'read'.
    """
    read_only_tools: List[Any] = []
    for tool in tools:
        if isinstance(tool, dict):
            raw_tier = tool.get("risk_tier")
        else:
            raw_tier = getattr(tool, "risk_tier", None)
        tier = str(raw_tier).strip().lower() if raw_tier else None
        if tier == "read":
            read_only_tools.append(tool)
    return read_only_tools

