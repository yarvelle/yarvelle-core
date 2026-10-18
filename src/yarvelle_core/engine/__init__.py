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

"""Yarvelle Core engine package.

Streamlined execution engine exposing GraphBuilder, AgentExecutionService,
prompt assembly, and runtime execution facade.
"""

from __future__ import annotations

from yarvelle_core.engine.agent_factory import (
    create_yarvelle_agent,
    load_all_subagents,
    load_subagent_from_yaml,
)
from yarvelle_core.engine.builder import GraphBuilder, create_agent_graph
from yarvelle_core.engine.prompt_builder import build_system_prompt
from yarvelle_core.engine.runner import ExecutionContext, execute_agent_run
from yarvelle_core.engine.service import AgentExecutionService

__all__ = [
    "AgentExecutionService",
    "ExecutionContext",
    "GraphBuilder",
    "build_system_prompt",
    "create_agent_graph",
    "create_yarvelle_agent",
    "execute_agent_run",
    "load_all_subagents",
    "load_subagent_from_yaml",
]
