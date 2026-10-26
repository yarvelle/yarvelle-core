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

"""State and schema definitions for the Dynamic MCP Database Toolbox Subgraph."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, TypedDict

from yarvelle_core.tools.db_query_planner import SqlQueryPlan
from yarvelle_core.tools.sql_ast_sandbox import (
    SqlOperation,
    SqlSecurityError,
    SqlValidationError,
    ValidatedSqlPlan,
)


class DbSubgraphState(TypedDict, total=False):
    """Typed state flowing through the Dynamic MCP Database Toolbox Subgraph."""

    request: str
    operation_hint: Optional[SqlOperation]
    allowed_operations: Sequence[SqlOperation]
    statement: Optional[str]
    parameters: Dict[str, Any]
    profile_id: str
    user_id: Optional[str]
    scope_ctx: Optional[Any]
    dialect: str
    pruned_tables: List[str]
    m_schema: str
    query_plan: Optional[Dict[str, Any]]
    validated_plan: Optional[Dict[str, Any]]
    validation_error: Optional[str]
    security_error: Optional[str]
    attempts: int
    max_retries: int
    result: Optional[Dict[str, Any]]
    status: Literal["pending", "needs_retry", "completed", "failed", "blocked"]


__all__ = [
    "DbSubgraphState",
    "SqlOperation",
    "SqlQueryPlan",
    "SqlSecurityError",
    "SqlValidationError",
    "ValidatedSqlPlan",
]
