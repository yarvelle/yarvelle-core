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

from typing import Any, Dict, List, Optional, Sequence

from yarvelle_core.engine.tool_exec import KNOWN_RISK_TIERS, PolicyDecision, ToolContext, ToolSpec


def derive_tool_risk_tier(
    tool_name: str,
    tool_registry: Optional[Any] = None,
    tools: Optional[Sequence[Any]] = None,
) -> str:
    """Deterministically derives the risk_tier for a tool, failing closed to 'irreversible'.

    Invariants:
    1. Never trusts model-reported risk tiers.
    2. Inspects candidate tools, ToolSpecRegistry, and default built-in registries.
    3. Fails closed to 'irreversible' if tool is unknown or declared tier is invalid.
    """
    clean_name = str(tool_name or "").strip()
    if not clean_name:
        return "irreversible"

    raw_tier: Optional[Any] = None

    # 1. Check candidate tools passed directly to the round
    if tools:
        for t in tools:
            t_name = t.get("name") if isinstance(t, dict) else getattr(t, "name", None)
            if t_name == clean_name:
                raw_tier = t.get("risk_tier") if isinstance(t, dict) else getattr(t, "risk_tier", None)
                if raw_tier:
                    break

    # 2. Check active ToolSpecRegistry
    if raw_tier is None and tool_registry is not None:
        get_fn = getattr(tool_registry, "get", None)
        if callable(get_fn):
            spec = get_fn(clean_name)
            if spec is not None:
                raw_tier = getattr(spec, "risk_tier", None)

    # 3. Check default built-in registry
    if raw_tier is None:
        try:
            from yarvelle_core.engine.tool_registry import create_default_registry

            default_reg = create_default_registry()
            spec = default_reg.get(clean_name)
            if spec is not None:
                raw_tier = getattr(spec, "risk_tier", None)
        except Exception:
            pass

    # 4. Check closed tool definitions
    if raw_tier is None:
        try:
            from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS

            def_dict = CLOSED_TOOL_DEFINITIONS.get(clean_name)
            if def_dict:
                raw_tier = def_dict.get("risk_tier")
        except Exception:
            pass

    # 5. Normalize and validate against known tiers
    if raw_tier:
        tier_str = str(raw_tier).strip().lower()
        if tier_str in KNOWN_RISK_TIERS:
            return tier_str

    # Fail closed
    return "irreversible"


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
        tool_name = spec.get("name", "unnamed")
    else:
        tool_name = getattr(spec, "name", "unnamed")

    tier = derive_tool_risk_tier(tool_name, tools=[spec] if spec else None)

    if tier == "read":
        return PolicyDecision.allow("Read operation permitted during deliberation rounds")

    return PolicyDecision.block(
        f"Non-read-tier tool '{tool_name}' with risk_tier '{tier}' is blocked "
        "during deliberation rounds. Only read-tier tools are permitted."
    )


def filter_read_only_tools(
    tools: Sequence[Any],
    tool_registry: Optional[Any] = None,
) -> List[Any]:
    """Filters candidate tools to only those with risk_tier == 'read'.

    Invariants:
    1. Unknown tiers fail closed; never infer 'read' if missing or non-string.
    2. Supports both ToolSpec/object instances and dictionary tool definitions.
    3. Case-insensitive comparison against 'read'.
    """
    read_only_tools: List[Any] = []
    for tool in tools:
        if isinstance(tool, dict):
            t_name = tool.get("name", "")
        else:
            t_name = getattr(tool, "name", "")
        tier = derive_tool_risk_tier(str(t_name), tool_registry=tool_registry, tools=[tool])
        if tier == "read":
            read_only_tools.append(tool)
    return read_only_tools


