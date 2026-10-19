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

"""Yarvelle Core Workflows Package.

Houses class-based LangGraph nodes, multi-agent subgraphs, and the unified
AgentState schema following SOLID principles.
"""

from __future__ import annotations

from yarvelle_core.workflows.dispatcher import ExecutionDispatcher
from yarvelle_core.workflows.nodes.base import BaseNode
from yarvelle_core.workflows.state import (
    AgentState,
    create_initial_state,
    extract_text_content,
    get_last_message,
    get_last_user_message,
    get_last_user_prompt_text,
)

__all__ = [
    "AgentState",
    "BaseNode",
    "ExecutionDispatcher",
    "create_initial_state",
    "extract_text_content",
    "get_last_message",
    "get_last_user_message",
    "get_last_user_prompt_text",
]
