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

"""M-Schema Guided Dynamic SQL Query Planner with Self-Correction Support.

Translates natural-language database requests (or repairs failed SQL drafts)
into parameterized DQL/DML plans (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) using
pruned M-Schema table, column, and index comments from SchemaCatalog.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from yarvelle_core.db.schema_catalog import (
    AUTO_INJECTED_COLUMNS,
    SchemaCatalog,
    TableSchemaDoc,
    get_schema_catalog,
)
from yarvelle_core.tools.sql_ast_sandbox import SqlOperation

logger = logging.getLogger(__name__)

QUERY_PLANNER_SYSTEM_PROMPT = """You are the Yarvelle Core Database Query Planner.
Your job is to translate a user or agent database operation request into a single, safe,
parameterized SQL statement using ONLY the provided M-Schema database documentation.

STRICT SECURITY & SQL GENERATION RULES:
1. ALLOWED OPERATIONS ONLY: You may ONLY generate `SELECT`, `INSERT`, `UPDATE`, or `DELETE`.
   NEVER generate DDL (`CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `RENAME`), DCL (`GRANT`, `REVOKE`),
   TCL (`BEGIN`, `COMMIT`, `ROLLBACK`), or administrative commands (`PRAGMA`, `ATTACH`, `VACUUM`).
2. SINGLE STATEMENT: Output exactly one SQL statement. Never stack multiple statements with `;`.
3. NAMED PARAMETER BINDINGS: Use colon-prefixed named parameters (`:param_name`) for all literal
   filter values and inserted/updated values, and populate their values in the `parameters` dict.
4. EXACT SCHEMA ADHERENCE: Use ONLY table and column names documented in the `【TABLE】` M-Schema blocks.
   Read column comments and `# Indexes:` comments carefully to choose the best filter and sort columns.
5. TENANT & SCOPE ISOLATION: `profile_id` and `scope` are automatically injected by the AST sandbox,
   so you do not need to manually bind them unless specifically filtering by a secondary column.
6. SAFE MUTATIONS: Every `UPDATE` and `DELETE` statement MUST include an explicit, non-tautological
   `WHERE` clause identifying the target row(s) (e.g., `WHERE id = :id` or `WHERE slug = :slug`).
"""


class SqlQueryPlan(BaseModel):
    """Structured SQL query plan produced by DbQueryPlanner."""

    operation: Literal["SELECT", "INSERT", "UPDATE", "DELETE"] = Field(
        description="SQL operation type: SELECT, INSERT, UPDATE, or DELETE."
    )
    target_tables: List[str] = Field(
        default_factory=list,
        description="Database table names referenced by the statement.",
    )
    statement: str = Field(
        description="Single parameterized SQL statement using :param placeholders."
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named parameter bindings corresponding to :param placeholders in statement.",
    )
    rationale: str = Field(
        default="",
        description="Concise explanation of the query plan and index/column selection.",
    )


def _infer_operation_from_text(
    text: str,
    operation_hint: Optional[SqlOperation] = None,
) -> SqlOperation:
    """Infer whether a natural-language request is SELECT, INSERT, UPDATE, or DELETE."""
    if operation_hint in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
        return operation_hint

    stripped = text.strip()
    upper_start = stripped.upper()
    for op in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        if upper_start.startswith(f"{op} "):
            return op  # type: ignore[return-value]

    lower = stripped.lower()
    if re.search(r"\b(delete|remove|purge|erase)\b", lower):
        return "DELETE"
    if re.search(r"\b(update|mark|change|modify|set|complete|snooze|rename)\b", lower):
        return "UPDATE"
    if re.search(r"\b(insert|create|add|record|save|schedule|log)\b", lower):
        return "INSERT"
    return "SELECT"


def _deterministic_nl_to_sql(
    request: str,
    *,
    operation_hint: Optional[SqlOperation],
    catalog: SchemaCatalog,
    scope_ctx: Optional[Any],
    extra_params: Optional[Dict[str, Any]] = None,
    previous_error: Optional[str] = None,
    previous_sql: Optional[str] = None,
) -> SqlQueryPlan:
    """Deterministic fallback query planner for offline environments and structured requests."""
    params: Dict[str, Any] = dict(extra_params or {})
    stripped = request.strip()

    # 1. If previous_sql failed due to an unknown column error and we can map it to a valid column:
    if previous_sql and previous_error and "Unknown column" in previous_error:
        m_bad = re.search(r"Unknown column '([^']+)' on table '([^']+)'", previous_error)
        if not m_bad:
            m_bad = re.search(
                r"Unknown column '([^']+)'.*Valid columns on '([^']+)'", previous_error
            )
        if m_bad:
            bad_col, tbl_name = m_bad.group(1), m_bad.group(2)
            t_doc = catalog.get_table_doc(tbl_name, scope_ctx=scope_ctx, mode="read")
            if t_doc:
                # Find closest column match by substring or semantic synonym
                replacement_col = _find_closest_column(bad_col, t_doc)
                if replacement_col:
                    repaired_sql = re.sub(
                        rf"\b{re.escape(bad_col)}\b", replacement_col, previous_sql
                    )
                    op = _infer_operation_from_text(repaired_sql, operation_hint)
                    return SqlQueryPlan(
                        operation=op,
                        target_tables=[t_doc.name],
                        statement=repaired_sql,
                        parameters=params,
                        rationale=(
                            f"Self-corrected unknown column '{bad_col}' to valid column "
                            f"'{replacement_col}' on table '{t_doc.name}' using M-Schema comments."
                        ),
                    )

    # 2. If request is already a raw SQL statement (SELECT / INSERT / UPDATE / DELETE):
    upper_prefix = stripped.upper()
    if upper_prefix.startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
        op = _infer_operation_from_text(stripped, operation_hint)
        pruned = catalog.prune_tables_for_intent(stripped, scope_ctx=scope_ctx, max_tables=4)
        return SqlQueryPlan(
            operation=op,
            target_tables=pruned[:1] if pruned else [],
            statement=stripped,
            parameters=params,
            rationale="Direct parameterized SQL statement validated against M-Schema.",
        )

    # 3. Synthesize parameterized SQL from natural language + M-Schema metadata
    op = _infer_operation_from_text(stripped, operation_hint)
    pruned_tables = catalog.prune_tables_for_intent(stripped, scope_ctx=scope_ctx, max_tables=4)
    mode: Literal["read", "write"] = "read" if op == "SELECT" else "write"
    accessible = catalog.get_accessible_tables(scope_ctx=scope_ctx, mode=mode)

    target_name = next((t for t in pruned_tables if t in accessible), None)
    if target_name is None:
        target_name = "notes" if "notes" in accessible else next(iter(accessible.keys()), "notes")
    t_doc = accessible.get(target_name) or catalog.get_table_doc(target_name)
    assert t_doc is not None

    if op == "SELECT":
        return _build_select_plan(stripped, t_doc, params)
    if op == "INSERT":
        return _build_insert_plan(stripped, t_doc, params)
    if op == "UPDATE":
        return _build_update_plan(stripped, t_doc, params)
    return _build_delete_plan(stripped, t_doc, params)


def _find_closest_column(bad_col: str, t_doc: TableSchemaDoc) -> Optional[str]:
    """Map a hallucinated column name to the closest real column on TableSchemaDoc."""
    bad_low = bad_col.lower()
    synonyms: Dict[str, List[str]] = {
        "body": ["content", "description", "notes", "instructions"],
        "text": ["content", "description", "body", "notes", "extracted_text"],
        "note": ["content", "notes", "description"],
        "due": ["next_due_at", "due_date", "end_time"],
        "due_at": ["next_due_at", "due_date"],
        "due_date": ["next_due_at", "due_date"],
        "name": ["title", "name", "account_name", "biller_name", "activity_name", "book_title"],
        "subject": ["title", "subject"],
        "state": ["status"],
        "kind": ["type", "category", "kind"],
        "category": ["category", "type"],
    }
    for key, candidates in synonyms.items():
        if key in bad_low or bad_low in key:
            for cand in candidates:
                if cand in t_doc.columns:
                    return cand

    for col_name in t_doc.columns:
        if col_name.lower() in bad_low or bad_low in col_name.lower():
            return col_name

    # Fallback to first non-auto-injected string/text column
    for col_name in t_doc.columns:
        if col_name not in AUTO_INJECTED_COLUMNS:
            return col_name
    return None


def _build_select_plan(
    request: str,
    t_doc: TableSchemaDoc,
    params: Dict[str, Any],
) -> SqlQueryPlan:
    col_names = list(t_doc.columns.keys())
    where_clauses: List[str] = []
    lower_req = request.lower()

    # Check common filter columns (status, category, type, slug, id)
    for filter_col in ("status", "category", "type", "slug", "id"):
        if filter_col in t_doc.columns:
            if filter_col in params:
                where_clauses.append(f"{filter_col} = :{filter_col}")
            else:
                c_doc = t_doc.columns[filter_col]
                for ex in c_doc.examples:
                    if re.search(rf"\b{re.escape(ex.lower())}\b", lower_req):
                        params[filter_col] = ex
                        where_clauses.append(f"{filter_col} = :{filter_col}")
                        break

    # Check quoted search term in request
    m_quote = re.search(r"['\"]([^'\"]{2,64})['\"]", request)
    if m_quote and not where_clauses:
        search_val = m_quote.group(1)
        for text_col in ("title", "slug", "name", "subject", "biller_name", "payee"):
            if text_col in t_doc.columns:
                params["search_term"] = f"%{search_val}%"
                where_clauses.append(f"{text_col} LIKE :search_term")
                break

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_col = (
        "next_due_at ASC"
        if "next_due_at" in t_doc.columns
        else "due_date ASC"
        if "due_date" in t_doc.columns
        else "updated_at DESC"
        if "updated_at" in t_doc.columns
        else "created_at DESC"
        if "created_at" in t_doc.columns
        else f"{col_names[0]} ASC"
    )
    sql = f"SELECT {', '.join(col_names)} FROM {t_doc.name}{where_sql} ORDER BY {order_col} LIMIT 50"
    return SqlQueryPlan(
        operation="SELECT",
        target_tables=[t_doc.name],
        statement=sql,
        parameters=params,
        rationale=f"Planned SELECT query on '{t_doc.name}' using M-Schema columns and index sort order ({order_col}).",
    )


def _build_insert_plan(
    request: str,
    t_doc: TableSchemaDoc,
    params: Dict[str, Any],
) -> SqlQueryPlan:
    insert_cols: List[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Extract quoted title/value if not already in params
    m_quote = re.findall(r"['\"]([^'\"]+)['\"]", request)
    for col_name, c_doc in t_doc.columns.items():
        if col_name in AUTO_INJECTED_COLUMNS:
            continue
        if col_name in params:
            insert_cols.append(col_name)
            continue
        if not c_doc.nullable or c_doc.default is not None:
            insert_cols.append(col_name)
            if col_name in {"title", "name", "subject", "account_name", "biller_name", "payee", "book_title", "activity_name"}:
                params[col_name] = m_quote[0] if m_quote else request[:80].strip()
            elif col_name == "slug":
                base_slug = re.sub(r"[^a-z0-9]+", "-", (m_quote[0] if m_quote else request[:40]).lower()).strip("-")
                params[col_name] = base_slug or "item"
            elif col_name in {"content", "body", "description", "notes"}:
                params[col_name] = m_quote[1] if len(m_quote) > 1 else request
            elif col_name in {"next_due_at", "due_date", "transaction_date", "start_time", "end_time", "achieved_on", "date_read"}:
                params[col_name] = now_iso
            elif c_doc.default is not None:
                params[col_name] = c_doc.default
            elif "INT" in c_doc.data_type.upper() or "NUMERIC" in c_doc.data_type.upper():
                params[col_name] = 0
            else:
                params[col_name] = ""

    placeholders = [f":{c}" for c in insert_cols]
    sql = f"INSERT INTO {t_doc.name} ({', '.join(insert_cols)}) VALUES ({', '.join(placeholders)})"
    return SqlQueryPlan(
        operation="INSERT",
        target_tables=[t_doc.name],
        statement=sql,
        parameters=params,
        rationale=f"Planned parameterized INSERT into '{t_doc.name}' with required schema columns.",
    )


def _build_update_plan(
    request: str,
    t_doc: TableSchemaDoc,
    params: Dict[str, Any],
) -> SqlQueryPlan:
    set_clauses: List[str] = []
    where_clauses: List[str] = []

    for filter_key in ("id", "slug"):
        if filter_key in params and filter_key in t_doc.columns:
            where_clauses.append(f"{filter_key} = :{filter_key}")

    for k in list(params.keys()):
        if k in t_doc.columns and k not in AUTO_INJECTED_COLUMNS and k not in {"id", "slug"}:
            set_clauses.append(f"{k} = :{k}")

    if not set_clauses:
        if "status" in t_doc.columns:
            params.setdefault("status", "completed")
            set_clauses.append("status = :status")
        elif "title" in t_doc.columns:
            params.setdefault("title", request[:80].strip())
            set_clauses.append("title = :title")

    if not where_clauses:
        m_quote = re.search(r"['\"]([^'\"]+)['\"]", request)
        if "slug" in t_doc.columns and m_quote:
            params.setdefault("target_slug", m_quote.group(1))
            where_clauses.append("slug = :target_slug")
        elif "id" in t_doc.columns and m_quote:
            params.setdefault("target_id", m_quote.group(1))
            where_clauses.append("id = :target_id")
        elif "title" in t_doc.columns and m_quote:
            params.setdefault("target_title", m_quote.group(1))
            where_clauses.append("title = :target_title")
        elif "id" in t_doc.columns:
            params.setdefault("id", params.get("id", "unknown-id"))
            where_clauses.append("id = :id")

    sql = f"UPDATE {t_doc.name} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"
    return SqlQueryPlan(
        operation="UPDATE",
        target_tables=[t_doc.name],
        statement=sql,
        parameters=params,
        rationale=f"Planned parameterized UPDATE on '{t_doc.name}' with explicit WHERE filter.",
    )


def _build_delete_plan(
    request: str,
    t_doc: TableSchemaDoc,
    params: Dict[str, Any],
) -> SqlQueryPlan:
    where_clauses: List[str] = []
    for filter_key in ("id", "slug", "title"):
        if filter_key in params and filter_key in t_doc.columns:
            where_clauses.append(f"{filter_key} = :{filter_key}")

    if not where_clauses:
        m_quote = re.search(r"['\"]([^'\"]+)['\"]", request)
        if m_quote:
            val = m_quote.group(1)
            if "slug" in t_doc.columns:
                params["slug"] = val
                where_clauses.append("slug = :slug")
            elif "id" in t_doc.columns:
                params["id"] = val
                where_clauses.append("id = :id")
            elif "title" in t_doc.columns:
                params["title"] = val
                where_clauses.append("title = :title")
        elif "id" in t_doc.columns:
            params.setdefault("id", "unknown-id")
            where_clauses.append("id = :id")

    sql = f"DELETE FROM {t_doc.name} WHERE {' AND '.join(where_clauses)}"
    return SqlQueryPlan(
        operation="DELETE",
        target_tables=[t_doc.name],
        statement=sql,
        parameters=params,
        rationale=f"Planned parameterized DELETE on '{t_doc.name}' with explicit WHERE filter.",
    )


class DbQueryPlanner:
    """Plans parameterized DQL/DML statements from natural language using M-Schema docs."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        schema_catalog: Optional[SchemaCatalog] = None,
    ) -> None:
        self.model = model
        self.schema_catalog = schema_catalog or get_schema_catalog()

    async def plan_query(
        self,
        request: str,
        *,
        operation_hint: Optional[SqlOperation] = None,
        parameters: Optional[Dict[str, Any]] = None,
        scope_ctx: Optional[Any] = None,
        dialect: str = "sqlite",
        previous_error: Optional[str] = None,
        previous_sql: Optional[str] = None,
    ) -> SqlQueryPlan:
        """Generate or repair a structured SqlQueryPlan for the given request."""
        pruned_tables = self.schema_catalog.prune_tables_for_intent(
            f"{request} {previous_sql or ''} {previous_error or ''}",
            scope_ctx=scope_ctx,
            max_tables=8,
        )
        m_schema = self.schema_catalog.get_m_schema(
            scope_ctx=scope_ctx,
            table_names=pruned_tables,
            dialect=dialect,
            include_indexes=True,
        )

        if self.model is not None:
            user_prompt_parts = [
                f"## M-Schema Database Documentation\n{m_schema}",
                f"## Operation Request\n{request}",
            ]
            if operation_hint:
                user_prompt_parts.append(f"## Required Operation Type\n{operation_hint}")
            if parameters:
                user_prompt_parts.append(
                    f"## Provided Parameter Bindings\n{json.dumps(parameters, default=str)}"
                )
            if previous_error:
                user_prompt_parts.append(
                    f"## Previous Validation / Execution Error (Please Self-Correct)\n"
                    f"Failed SQL: `{previous_sql}`\nError: `{previous_error}`\n"
                    "Fix the table/column names or syntax strictly using the M-Schema above."
                )

            messages = [
                SystemMessage(content=QUERY_PLANNER_SYSTEM_PROMPT),
                HumanMessage(content="\n\n".join(user_prompt_parts)),
            ]

            try:
                structured_llm = self.model.with_structured_output(SqlQueryPlan)
                plan_res = await structured_llm.ainvoke(messages)
                if isinstance(plan_res, SqlQueryPlan):
                    merged_params = dict(parameters or {})
                    merged_params.update(plan_res.parameters)
                    plan_res.parameters = merged_params
                    return plan_res
                if isinstance(plan_res, dict):
                    merged_params = dict(parameters or {})
                    merged_params.update(plan_res.get("parameters") or {})
                    plan_res["parameters"] = merged_params
                    return SqlQueryPlan.model_validate(plan_res)
            except Exception as exc:
                logger.debug("Structured LLM query planning fallback triggered: %s", exc)

        return _deterministic_nl_to_sql(
            request,
            operation_hint=operation_hint,
            catalog=self.schema_catalog,
            scope_ctx=scope_ctx,
            extra_params=parameters,
            previous_error=previous_error,
            previous_sql=previous_sql,
        )


__all__ = [
    "DbQueryPlanner",
    "QUERY_PLANNER_SYSTEM_PROMPT",
    "SqlQueryPlan",
]
