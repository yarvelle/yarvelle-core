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

"""Delegation meta-tools for dynamic orchestrator routing (Feature F-50 & Milestone 6).

Exports:
- ListAgentsTool: searches the AgentRegistry catalog for specialist agents and capabilities.
- DelegateToAgentTool: signals LangGraph dynamic routing to a target specialist agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from yarvelle_core.constants.agents import (
    AGENT_ORCHESTRATOR,
    TOOL_DELEGATE_TO_AGENT,
    TOOL_LIST_AGENTS,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 1. ListAgentsTool
# ============================================================================

class ListAgentsInput(BaseModel):
    """Input argument schema for ListAgentsTool (optional catalog search)."""

    query: str = Field(
        default="",
        description="Optional keywords to match against agent ids, titles, descriptions and tags. Empty lists all.",
    )
    limit: Optional[int] = Field(default=None, ge=1, le=50, description="Maximum number of agents to return.")


class ListAgentsTool(BaseTool):
    """LangChain tool for searching the live agent catalog (AgentRegistry)."""

    name: str = TOOL_LIST_AGENTS
    description: str = (
        "Search the available specialist agents and their capabilities in the live agent catalog. "
        "Pass keywords in `query` to narrow the list, or leave it empty to list every agent."
    )
    args_schema: Type[BaseModel] = ListAgentsInput
    registry: Any = None

    def __init__(self, registry: Any = None, **kwargs: Any) -> None:
        super().__init__(registry=registry, **kwargs)

    def _registry(self) -> Any:
        if self.registry is not None:
            return self.registry
        from yarvelle_core.agents.registry import get_agent_registry

        return get_agent_registry()

    def _run(self, query: str = "", limit: Optional[int] = None, **kwargs: Any) -> str:
        """Formats matching catalog entries from the registry (the only agent source)."""
        registry = self._registry()
        if hasattr(registry, "search"):
            matches = registry.search(query or "", limit=limit, exclude=AGENT_ORCHESTRATOR)
            if matches:
                return registry.format_agent_catalog(agents=matches)
            if query:
                return f"No agents match {query!r}. Call list_agents with an empty query to see all agents."
        elif hasattr(registry, "format_agent_catalog"):
            catalog = registry.format_agent_catalog(exclude=AGENT_ORCHESTRATOR)
            if catalog:
                return catalog
        return "No agents registered. Domain packs register specialist agents via Pack API v1."

    async def _arun(self, query: str = "", limit: Optional[int] = None, **kwargs: Any) -> str:
        """Asynchronous execution delegating to _run."""
        return self._run(query=query, limit=limit, **kwargs)


# ============================================================================
# 2. DelegateToAgentTool
# ============================================================================

class DelegateToAgentInput(BaseModel):
    """Input argument schema for DelegateToAgentTool."""

    agent_id: str = Field(
        ...,
        description="The unique identifier of the target specialist agent to delegate to.",
    )
    instructions: str = Field(
        default="",
        description="Specific instructions, goals, questions, or context for the delegated specialist agent.",
    )


class DelegateToAgentTool(BaseTool):
    """LangChain tool signaling the orchestrator graph to route execution to a specialist agent.

    The tool call output is intercepted by the Orchestrator / Graph edge router to transition
    state['current_agent'] and state['routed_subgraph'].
    """

    name: str = TOOL_DELEGATE_TO_AGENT
    description: str = (
        "Signal LangGraph to dynamically route execution to a specific specialist agent "
        "registered in the active catalog or pack."
    )
    args_schema: Type[BaseModel] = DelegateToAgentInput

    def _run(self, agent_id: str, instructions: str = "", **kwargs: Any) -> str:
        """Emit JSON delegation directive for graph transition."""
        payload = {
            "status": "delegated",
            "agent_id": agent_id.strip(),
            "instructions": instructions.strip(),
        }
        return json.dumps(payload)

    async def _arun(self, agent_id: str, instructions: str = "", **kwargs: Any) -> str:
        """Asynchronous delegation directive emission."""
        return self._run(agent_id=agent_id, instructions=instructions, **kwargs)


__all__ = [
    "DelegateToAgentInput",
    "DelegateToAgentTool",
    "ListAgentsInput",
    "ListAgentsTool",
]
