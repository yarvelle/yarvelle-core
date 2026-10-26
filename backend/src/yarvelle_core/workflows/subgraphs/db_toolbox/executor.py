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

"""Deterministic AST Validation, Pre-flight EXPLAIN, and Execution Node for DB Toolbox Subgraph."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.db.schema_catalog import SchemaCatalog, get_schema_catalog
from yarvelle_core.db.session import get_session_factory
from yarvelle_core.tools.mcp_db_toolbox import (
    _detect_session_dialect,
    _resolve_and_ensure_profile_id,
)
from yarvelle_core.tools.sql_ast_sandbox import (
    SqlSecurityError,
    SqlValidationError,
    validate_and_rewrite_sql,
)
from yarvelle_core.workflows.subgraphs.db_toolbox.schemas import DbSubgraphState

logger = logging.getLogger(__name__)


def create_query_executor_node(
    schema_catalog: Optional[SchemaCatalog] = None,
    session: Optional[AsyncSession] = None,
) -> Callable[[DbSubgraphState], Coroutine[Any, Any, Dict[str, Any]]]:
    """Build the deterministic AST sandbox validation and SQLAlchemy execution node."""
    catalog = schema_catalog or get_schema_catalog()

    async def _execute_with_session(
        active_session: AsyncSession,
        state: DbSubgraphState,
    ) -> Dict[str, Any]:
        raw_profile_id = str(state.get("profile_id") or "").strip()
        if not raw_profile_id:
            raise ValueError("profile_id is strictly required for DB subgraph execution.")

        resolved_profile_id = await _resolve_and_ensure_profile_id(
            active_session, raw_profile_id
        )
        target_dialect = state.get("dialect") or _detect_session_dialect(active_session)
        scope_ctx = state.get("scope_ctx")
        allowed_ops = state.get("allowed_operations")
        stmt = state.get("statement") or ""
        params = dict(state.get("parameters") or {})
        attempts = int(state.get("attempts") or 1)
        max_retries = int(state.get("max_retries", 2))

        try:
            validated = validate_and_rewrite_sql(
                stmt,
                params,
                profile_id=resolved_profile_id,
                scope_ctx=scope_ctx,
                schema_catalog=catalog,
                source_dialect=target_dialect,
                target_dialect=target_dialect,
                allowed_operations=allowed_ops,
            )

            if validated.operation == "SELECT" and target_dialect == "sqlite":
                await active_session.execute(
                    text(f"EXPLAIN QUERY PLAN {validated.rewritten_sql}"),
                    validated.bound_params,
                )

            exec_result = await active_session.execute(
                text(validated.rewritten_sql),
                validated.bound_params,
            )

            plan_dict = state.get("query_plan") or {}
            rationale = plan_dict.get("rationale", "")

            if validated.operation == "SELECT":
                rows = [dict(r) for r in exec_result.mappings().all()]
                payload = {
                    "status": "ok",
                    "operation": validated.operation,
                    "risk_tier": validated.risk_tier,
                    "dialect": validated.dialect,
                    "target_tables": validated.target_tables,
                    "rewritten_sql": validated.rewritten_sql,
                    "rationale": rationale,
                    "attempts": attempts,
                    "count": len(rows),
                    "records": rows,
                }
            else:
                affected = (
                    exec_result.rowcount
                    if exec_result.rowcount is not None and exec_result.rowcount >= 0
                    else 0
                )
                returned_rows: List[Dict[str, Any]] = []
                if exec_result.returns_rows:
                    returned_rows = [dict(r) for r in exec_result.mappings().all()]
                    affected = max(affected, len(returned_rows))
                await active_session.commit()

                payload = {
                    "status": "ok",
                    "operation": validated.operation,
                    "risk_tier": validated.risk_tier,
                    "dialect": validated.dialect,
                    "target_tables": validated.target_tables,
                    "rewritten_sql": validated.rewritten_sql,
                    "rationale": rationale,
                    "attempts": attempts,
                    "affected_rows": affected,
                    "record": (
                        returned_rows[0]
                        if len(returned_rows) == 1
                        else (
                            {"id": validated.bound_params.get("__ctx_id")}
                            if validated.operation == "INSERT"
                            and "__ctx_id" in validated.bound_params
                            else None
                        )
                    ),
                    "records": returned_rows,
                }

            return {
                "validated_plan": {
                    "operation": validated.operation,
                    "risk_tier": validated.risk_tier,
                    "target_tables": validated.target_tables,
                    "rewritten_sql": validated.rewritten_sql,
                    "dialect": validated.dialect,
                },
                "result": payload,
                "validation_error": None,
                "security_error": None,
                "status": "completed",
            }

        except SqlSecurityError as sec_exc:
            # Security errors never retry; fail closed immediately
            return {
                "security_error": str(sec_exc),
                "validation_error": None,
                "status": "blocked",
                "result": {
                    "status": "blocked",
                    "error": str(sec_exc),
                },
            }
        except (SqlValidationError, Exception) as val_exc:
            err_msg = str(val_exc)
            if attempts <= max_retries:
                logger.info(
                    "DB subgraph scheduling planner self-correction (attempt %d/%d): %s",
                    attempts,
                    max_retries + 1,
                    err_msg,
                )
                return {
                    "validation_error": err_msg,
                    "status": "needs_retry",
                }
            return {
                "validation_error": err_msg,
                "status": "failed",
                "result": {
                    "status": "failed",
                    "error": err_msg,
                    "attempts": attempts,
                },
            }

    async def execute_query_node(state: DbSubgraphState) -> Dict[str, Any]:
        if session is not None:
            return await _execute_with_session(session, state)
        factory = get_session_factory()
        async with factory() as managed_session:
            return await _execute_with_session(managed_session, state)

    return execute_query_node


__all__ = ["create_query_executor_node"]
