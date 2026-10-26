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

"""Schema Introspection and Query Planner Nodes for the DB Toolbox Subgraph."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from yarvelle_core.db.schema_catalog import SchemaCatalog, get_schema_catalog
from yarvelle_core.scope.context import DEFAULT_SCOPE, ScopeContext
from yarvelle_core.tools.db_query_planner import DbQueryPlanner
from yarvelle_core.workflows.subgraphs.db_toolbox.schemas import DbSubgraphState


def create_schema_introspection_node(
    schema_catalog: Optional[SchemaCatalog] = None,
) -> Callable[[DbSubgraphState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Build the schema introspection node that prunes tables and renders M-Schema docs."""
    catalog = schema_catalog or get_schema_catalog()

    async def introspect_schema_node(state: DbSubgraphState) -> Dict[str, Any]:
        profile_id = str(state.get("profile_id") or "").strip()
        scope_ctx = state.get("scope_ctx")
        if scope_ctx is None and profile_id:
            scope_ctx = ScopeContext(
                profile_id=profile_id,
                scope=DEFAULT_SCOPE,
                actor=state.get("user_id"),
            )

        dialect = state.get("dialect") or "sqlite"
        intent_text = f"{state.get('request') or ''} {state.get('statement') or ''}".strip()
        pruned_tables = catalog.prune_tables_for_intent(
            intent_text, scope_ctx=scope_ctx, max_tables=8
        )
        m_schema = catalog.get_m_schema(
            scope_ctx=scope_ctx,
            table_names=pruned_tables,
            dialect=dialect,
            include_indexes=True,
        )
        return {
            "scope_ctx": scope_ctx,
            "pruned_tables": pruned_tables,
            "m_schema": m_schema,
            "attempts": int(state.get("attempts") or 0),
            "max_retries": int(state.get("max_retries", 2)),
            "status": "pending",
        }

    return introspect_schema_node


def create_query_planner_node(
    model: Optional[BaseChatModel] = None,
    schema_catalog: Optional[SchemaCatalog] = None,
) -> Callable[[DbSubgraphState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Build the M-Schema guided query planner node with self-correction support."""
    catalog = schema_catalog or get_schema_catalog()
    planner = DbQueryPlanner(model=model, schema_catalog=catalog)

    async def plan_query_node(state: DbSubgraphState) -> Dict[str, Any]:
        attempts = int(state.get("attempts") or 0) + 1
        current_stmt = state.get("statement")
        current_params = dict(state.get("parameters") or {})
        validation_error = state.get("validation_error")
        op_hint = state.get("operation_hint")
        scope_ctx = state.get("scope_ctx")
        dialect = state.get("dialect") or "sqlite"

        # If caller supplied an explicit SQL statement on first attempt and no error occurred yet:
        if current_stmt and attempts == 1 and not validation_error:
            return {
                "attempts": attempts,
                "statement": current_stmt,
                "parameters": current_params,
                "query_plan": {
                    "operation": op_hint or "SELECT",
                    "target_tables": state.get("pruned_tables", []),
                    "statement": current_stmt,
                    "parameters": current_params,
                    "rationale": "Direct parameterized SQL statement.",
                },
            }

        request_text = state.get("request") or current_stmt or ""
        plan = await planner.plan_query(
            request_text,
            operation_hint=op_hint,
            parameters=current_params,
            scope_ctx=scope_ctx,
            dialect=dialect,
            previous_error=validation_error,
            previous_sql=current_stmt,
        )
        return {
            "attempts": attempts,
            "statement": plan.statement,
            "parameters": plan.parameters,
            "query_plan": plan.model_dump(),
            "validation_error": None,
        }

    return plan_query_node


__all__ = [
    "create_query_planner_node",
    "create_schema_introspection_node",
]
