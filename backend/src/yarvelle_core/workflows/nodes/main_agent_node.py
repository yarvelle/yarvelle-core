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

"""Graph node that runs the main agent for model-routed turns.

The main agent hands work to registered agents through the Deep Agents
``task`` tool (see ``yarvelle_core.engine.orchestration``). If it fails and
the pack has a default agent, the turn is handed to that agent with a notice.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID, HybridRouter, ToolResolver
from yarvelle_core.engine.orchestration.task_guard import AuditSink, TaskStatusSink
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteSource
from yarvelle_core.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


class MainAgentNode(BaseNode):
    """Runs the guarded main agent and returns its new messages."""

    def __init__(
        self,
        *,
        model: Optional[BaseChatModel],
        registry: AgentRegistry,
        orchestration: Optional[PackOrchestrationSpec] = None,
        default_agent: Optional[str] = None,
        audit_sink: Optional[AuditSink] = None,
        status_sink: Optional[TaskStatusSink] = None,
        tool_resolver: Optional[ToolResolver] = None,
        name: str = "main_agent",
    ) -> None:
        super().__init__(name=name)
        self.router = HybridRouter(
            registry=registry,
            model=model,
            spec=orchestration,
            default_agent=default_agent,
            audit_sink=audit_sink,
            status_sink=status_sink,
            tool_resolver=tool_resolver,
        )

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        outcome = await self.router.run(state, thread_id=state.get("thread_id"))
        if outcome is None:
            return {"error": "No agent could take this turn.", "next_step": "error"}
        notices = [n.model_dump(mode="json") for n in outcome.notices]
        result: Dict[str, Any] = {
            "route_decision": outcome.decision.model_dump(mode="json", exclude_none=True),
        }
        if notices:
            result["orchestration_notices"] = list(state.get("orchestration_notices") or []) + notices
        if outcome.decision.source == RouteSource.MAIN_AGENT:
            result.update(
                messages=outcome.messages,
                current_agent=MAIN_AGENT_ID,
                agent_id=MAIN_AGENT_ID,
                next_step="output_guardrail",
            )
            return result
        # Fallback: the chosen agent runs on the normal agent path.
        target = outcome.decision.agent_id or ""
        result.update(current_agent=target, routed_subgraph=target, agent_id=target, next_step="agent")
        return result


__all__ = ["MainAgentNode"]
