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

"""Required middleware hook points for every Deep Agents subagent spec.

Isolated subagents do not inherit the main agent's custom middleware (ADR-0005,
2026-11-03 amendment), so the registry attaches these hooks to every spec it
builds and refuses to hand out a spec without them.

Both hooks are pass-through placeholders for now: the tool-policy gate
(ADR-0006) fills in :class:`SubagentToolPolicyHook` and per-hand-off audit
fills in :class:`SubagentAuditHook`. Their names and the enforcement check are
the stable contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple, Type

from langchain.agents.middleware import AgentMiddleware

from yarvelle_core.agents.errors import SubagentHookError


class _SubagentHook(AgentMiddleware):
    """Base for the required per-subagent hooks; bound to one agent id."""

    hook_kind: str = ""

    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id

    @property
    def name(self) -> str:
        return f"yarvelle_{self.hook_kind}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(agent_id={self.agent_id!r})"


class SubagentToolPolicyHook(_SubagentHook):
    """Hook point for the tool-policy gate on a subagent (pass-through for now)."""

    hook_kind = "tool_policy"


class SubagentAuditHook(_SubagentHook):
    """Hook point for per-hand-off audit on a subagent (pass-through for now)."""

    hook_kind = "audit"


REQUIRED_SUBAGENT_HOOKS: Tuple[Type[_SubagentHook], ...] = (SubagentToolPolicyHook, SubagentAuditHook)


def required_subagent_middleware(agent_id: str) -> List[AgentMiddleware]:
    """Returns fresh instances of every required hook for agent_id, in a fixed order."""
    return [hook(agent_id) for hook in REQUIRED_SUBAGENT_HOOKS]


def missing_subagent_hooks(spec: Mapping[str, Any]) -> List[str]:
    """Returns the names of required hooks absent from spec (or bound to another agent)."""
    middleware: Sequence[Any] = spec.get("middleware") or ()
    name = spec.get("name")
    missing: List[str] = []
    for hook in REQUIRED_SUBAGENT_HOOKS:
        if not any(isinstance(m, hook) and m.agent_id == name for m in middleware):
            missing.append(hook.__name__)
    return missing


def ensure_subagent_hooks(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Raises SubagentHookError unless spec carries every required hook; returns spec."""
    missing = missing_subagent_hooks(spec)
    if missing:
        raise SubagentHookError(
            f"Subagent {spec.get('name')!r} is missing required middleware: {', '.join(missing)}"
        )
    return spec


__all__ = [
    "REQUIRED_SUBAGENT_HOOKS",
    "SubagentAuditHook",
    "SubagentToolPolicyHook",
    "ensure_subagent_hooks",
    "missing_subagent_hooks",
    "required_subagent_middleware",
]
