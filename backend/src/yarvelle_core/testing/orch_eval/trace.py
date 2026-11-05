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

"""What one turn did, as seen from the graph's state, stream and audit records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TaskRecord:
    """One hand-off (one ``task`` tool call) and the states it went through.

    A call the guard refused before the agent started (an unknown or hidden
    agent, for example) has no ``started`` state.
    """

    task_id: str
    agent_id: str
    states: List[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def final_state(self) -> str:
        return self.states[-1] if self.states else "started"


@dataclass
class TurnTrace:
    """Everything the checks look at for one turn."""

    turn: int
    user: str
    route: Optional[str] = None
    route_agent: Optional[str] = None
    agents: List[str] = field(default_factory=list)
    tasks: List[TaskRecord] = field(default_factory=list)
    rejected_tasks: List[TaskRecord] = field(default_factory=list)
    status_events: List[Dict[str, Any]] = field(default_factory=list)
    notices: List[Dict[str, Any]] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    guardrail_flags: List[str] = field(default_factory=list)
    route_events: List[str] = field(default_factory=list)
    turn_tasks: List[Dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    nodes: List[str] = field(default_factory=list)
    model_calls: int = 0
    model_calls_before_route: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    subagent_token_leaks: List[str] = field(default_factory=list)
    script_problems: List[str] = field(default_factory=list)
    cancelled: bool = False
    error: Optional[str] = None

    @property
    def task_calls(self) -> int:
        """Hand-offs that started. Refused calls are in ``rejected_tasks``."""
        return len(self.tasks)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def notice_codes(self) -> List[str]:
        return [str(n.get("code")) for n in self.notices]

    def final_states(self) -> Dict[str, str]:
        """Final task state per agent (the last hand-off to it wins)."""
        out: Dict[str, str] = {}
        for task in self.tasks:
            out[task.agent_id] = task.final_state
        return out

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["task_calls"] = self.task_calls
        data["tokens"] = self.tokens
        data.pop("status_events", None)
        return data


__all__ = ["TaskRecord", "TurnTrace"]
