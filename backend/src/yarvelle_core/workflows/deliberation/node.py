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

"""Graph node that runs a deliberation panel for a ``deliberate`` plan.

Every other multi-agent turn runs in the main agent (Deep Agents ``task``
hand-offs); this node only hosts the bounded deliberation engine.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel

from yarvelle_core.agents.registry import AgentRegistry, get_agent_registry
from yarvelle_core.workflows.deliberation.engine import DeliberationEngine
from yarvelle_core.workflows.nodes.base import BaseNode


class DeliberationNode(BaseNode):
    """Runs ``DeliberationEngine`` with the plan's deliberation config."""

    def __init__(
        self,
        *,
        model: Optional[BaseChatModel] = None,
        registry: Optional[AgentRegistry] = None,
        tool_registry: Optional[Any] = None,
        default_tools: Optional[Sequence[Any]] = None,
        name: str = "deliberation",
    ) -> None:
        super().__init__(name=name)
        self.model = model
        self._registry = registry
        self.tool_registry = tool_registry
        self.default_tools = list(default_tools) if default_tools is not None else None

    @property
    def registry(self) -> AgentRegistry:
        if self._registry is None:
            self._registry = get_agent_registry()
        return self._registry

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        plan = state.get("execution_plan")
        config = plan.get("deliberation_config") if isinstance(plan, dict) else getattr(plan, "deliberation_config", None)
        engine = DeliberationEngine(
            model=self.model or state.get("model"),
            registry=self.registry,
            tool_registry=self.tool_registry,
            default_tools=self.default_tools,
            config=config,
            session=state.get("session") or state.get("db_session"),
            session_factory=state.get("session_factory"),
        )
        res_state = await engine.run(state)  # type: ignore[arg-type]
        outputs = dict(res_state.get("specialist_outputs") or {})
        result: Dict[str, Any] = {"specialist_outputs": outputs, "next_step": "response_synthesizer"}
        if res_state.get("deliberation_state") is not None:
            result["deliberation_state"] = res_state["deliberation_state"]
        if res_state.get("output"):
            result["output"] = res_state["output"]
        return result


__all__ = ["DeliberationNode"]
