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

"""Errors raised by the agent registry. Unknown ids are never replaced with a default."""

from __future__ import annotations

from typing import Iterable, List, Sequence


class AgentNotFoundError(KeyError):
    """Raised when an agent id is missing, malformed, or not in the catalog."""

    def __init__(self, agent_id: object, available: Iterable[str] = ()) -> None:
        self.agent_id = agent_id
        self.available: List[str] = sorted(available)
        super().__init__(agent_id)

    def __str__(self) -> str:
        shown = ", ".join(self.available[:20]) if self.available else "none"
        more = f" (+{len(self.available) - 20} more)" if len(self.available) > 20 else ""
        return f"Unknown agent id {self.agent_id!r}; registered agents: {shown}{more}"


class DuplicateAgentError(ValueError):
    """Raised when two agents of the same source kind share an id."""

    def __init__(self, agent_id: str, origins: Sequence[str]) -> None:
        self.agent_id = agent_id
        self.origins = list(origins)
        super().__init__(f"Duplicate agent id {agent_id!r} defined in: {', '.join(self.origins)}")


class SubagentHookError(RuntimeError):
    """Raised when a subagent spec lacks the required policy or audit middleware."""


__all__ = ["AgentNotFoundError", "DuplicateAgentError", "SubagentHookError"]
