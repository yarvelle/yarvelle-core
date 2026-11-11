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

"""Errors raised by the agent registry bridged onto YarvelleError."""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence

from yarvelle_core.errors.base import YarvelleError


class AgentNotFoundError(YarvelleError, KeyError):
    """Raised when an agent id is missing, malformed, or not in the catalog."""

    DEFAULT_ERROR_CODE = "YRV-800-001"

    def __init__(
        self,
        agent_id: object,
        available: Iterable[str] = (),
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.agent_id = agent_id
        self.available: List[str] = sorted(available)
        super().__init__(
            self.DEFAULT_ERROR_CODE,
            context={"agent_id": str(agent_id)},
            cause=cause,
        )

    @property
    def detail(self) -> str:
        shown = ", ".join(self.available[:20]) if self.available else "none"
        more = f" (+{len(self.available) - 20} more)" if len(self.available) > 20 else ""
        return f"Unknown agent id {self.agent_id!r}; registered agents: {shown}{more}"


class DuplicateAgentError(YarvelleError, ValueError):
    """Raised when two agents of the same source kind share an id."""

    DEFAULT_ERROR_CODE = "YRV-800-002"

    def __init__(
        self,
        agent_id: str,
        origins: Sequence[str],
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.agent_id = agent_id
        self.origins = list(origins)
        msg = f"Duplicate agent id {self.agent_id!r} defined in: {', '.join(self.origins)}"
        super().__init__(
            self.DEFAULT_ERROR_CODE,
            context={"agent_id": agent_id, "origins": list(self.origins)},
            cause=cause,
            detail=msg,
        )


class SubagentHookError(YarvelleError, RuntimeError):
    """Raised when a subagent spec lacks the required policy or audit middleware."""

    DEFAULT_ERROR_CODE = "YRV-800-003"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            self.DEFAULT_ERROR_CODE,
            context=context,
            cause=cause,
            detail=str(message) if message is not None else None,
        )


__all__ = ["AgentNotFoundError", "DuplicateAgentError", "SubagentHookError"]
