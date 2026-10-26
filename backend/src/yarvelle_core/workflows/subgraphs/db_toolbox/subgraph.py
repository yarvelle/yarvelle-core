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

"""LangGraph StateGraph builder for the Dynamic MCP Database Toolbox Subgraph."""

from __future__ import annotations

from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.db.schema_catalog import SchemaCatalog
from yarvelle_core.workflows.subgraphs.db_toolbox.executor import (
    create_query_executor_node,
)
from yarvelle_core.workflows.subgraphs.db_toolbox.planner import (
    create_query_planner_node,
    create_schema_introspection_node,
)
from yarvelle_core.workflows.subgraphs.db_toolbox.schemas import DbSubgraphState


def _route_after_execution(state: DbSubgraphState) -> str:
    """Route back to `plan_query` when recoverable schema/syntax errors occur and retries remain."""
    if state.get("status") == "needs_retry":
        return "plan_query"
    return END


def build_db_toolbox_subgraph(
    *,
    model: Optional[BaseChatModel] = None,
    schema_catalog: Optional[SchemaCatalog] = None,
    session: Optional[AsyncSession] = None,
) -> CompiledStateGraph:
    """Compile the 2-stage Plan -> AST Validate & Execute -> Self-Correct LangGraph subgraph."""
    graph = StateGraph(DbSubgraphState)

    graph.add_node(
        "introspect_schema",
        create_schema_introspection_node(schema_catalog=schema_catalog),
    )
    graph.add_node(
        "plan_query",
        create_query_planner_node(model=model, schema_catalog=schema_catalog),
    )
    graph.add_node(
        "validate_and_execute",
        create_query_executor_node(schema_catalog=schema_catalog, session=session),
    )

    graph.add_edge(START, "introspect_schema")
    graph.add_edge("introspect_schema", "plan_query")
    graph.add_edge("plan_query", "validate_and_execute")
    graph.add_conditional_edges(
        "validate_and_execute",
        _route_after_execution,
        {
            "plan_query": "plan_query",
            END: END,
        },
    )

    return graph.compile()


__all__ = ["build_db_toolbox_subgraph"]
