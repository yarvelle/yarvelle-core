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

"""Declarative & Dynamic MCP Database Toolbox for Yarvelle Core Agents.

Provides two complementary execution paths over any SQLAlchemy-supported SQL database
(SQLite, PostgreSQL, MySQL/MariaDB, MS SQL Server, DuckDB):
1. Declarative Fast-Path Tools: Loaded from `resources/db_tools.yaml` (and pack-registered
   YAML files) with strict Pydantic input schemas and parameterized SQL templates.
2. Dynamic AST-Sandboxed Query Planner & Executor: Exposes `db_inspect_schema`,
   `db_execute_query` (SELECT), and `db_mutate_records` (INSERT, UPDATE, DELETE)
   backed by `SchemaCatalog` M-Schema documentation, `DbQueryPlanner`, and the
   5-stage `SqlAstSandbox` firewall with a 2-retry self-correction loop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Union,
)
import uuid

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model
import sqlglot
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import yaml

from yarvelle_core.connectors.mcp_remote import compute_mcp_schema_hash
from yarvelle_core.db.models import Job, Note, Profile
from yarvelle_core.db.schema_catalog import (
    SchemaCatalog,
    get_schema_catalog,
)
from yarvelle_core.db.session import get_session_factory
from yarvelle_core.engine.tool_registry import (
    DataFlows,
    RiskTier,
    ToolSpec,
    ToolSpecRegistry,
)
from yarvelle_core.i18n import DEFAULT_LOCALE, canonicalize_locale, normalize_text_nfc
from yarvelle_core.scope.context import DEFAULT_SCOPE, ScopeContext, scope_context
from yarvelle_core.tools.db_query_planner import DbQueryPlanner, SqlQueryPlan
from yarvelle_core.tools.sql_ast_sandbox import (
    SqlOperation,
    SqlSecurityError,
    SqlValidationError,
    ValidatedSqlPlan,
    normalize_sqlglot_dialect,
    validate_and_rewrite_sql,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_TOOLS_YAML_PATH = (
    Path(__file__).resolve().parents[1] / "resources" / "db_tools.yaml"
)

# Context-bound SQL parameters that must NEVER be controlled by LLM arguments
RESERVED_CONTEXT_PARAMS: Set[str] = {
    "profile_id",
    "user_id",
    "id",
    "scope",
    "locale",
    "now",
    "content_hash",
}

DYNAMIC_DB_TOOL_NAMES: Set[str] = {
    "db_inspect_schema",
    "db_execute_query",
    "db_mutate_records",
}

SqlSourceKind = Literal[
    "sql",
    "sqlite",
    "postgres",
    "postgresql",
    "mysql",
    "mariadb",
    "mssql",
    "tsql",
    "duckdb",
]

SqlToolKind = Literal[
    "sql",
    "sqlite-sql",
    "postgres-sql",
    "postgresql-sql",
    "mysql-sql",
    "mariadb-sql",
    "mssql-sql",
    "tsql-sql",
    "duckdb-sql",
]

DbToolHookFn = Callable[
    [str, Dict[str, Any], Optional[str], Optional[str], AsyncSession],
    Awaitable[Optional[Dict[str, Any]]],
]

_REGISTERED_TOOL_HOOKS: Dict[str, DbToolHookFn] = {}
_REGISTERED_PACK_YAML_PATHS: List[Path] = []


def register_db_tool_hook(tool_name: str, hook_fn: DbToolHookFn) -> None:
    """Register a domain-pack execution hook for a named declarative DB tool."""
    _REGISTERED_TOOL_HOOKS[tool_name.strip()] = hook_fn


def register_db_tools_yaml(yaml_path: Union[str, Path]) -> None:
    """Register an additional domain-pack db_tools.yaml manifest."""
    resolved = Path(yaml_path).resolve()
    if resolved not in _REGISTERED_PACK_YAML_PATHS:
        _REGISTERED_PACK_YAML_PATHS.append(resolved)


class DbParameterSpec(BaseModel):
    """Parameter specification inside a declarative db_tools.yaml tool."""

    name: str = Field(..., min_length=1)
    type: Literal["string", "integer", "number", "boolean", "array", "object"] = "string"
    description: str = ""
    required: bool = True
    default: Optional[Any] = None


# Backward-compatible alias
DbToolParameter = DbParameterSpec


class DbSourceConfig(BaseModel):
    """Database connection source metadata supporting any SQL dialect."""

    kind: SqlSourceKind = "sql"
    database: str = ""
    database_env: str = "DATABASE_URL"
    host: Optional[str] = None
    port: Optional[Union[int, str]] = None
    description: str = ""


class DbToolConfig(BaseModel):
    """Declarative SQL tool definition."""

    kind: SqlToolKind = "sql"
    source: str = "yarvelle-db"
    risk_tier: RiskTier = "read"
    entity: str = "record"
    description: str = ""
    statement: str = Field(..., min_length=1)
    parameters: List[DbParameterSpec] = Field(default_factory=list)

    def to_json_schema(self) -> Dict[str, Any]:
        """Builds the LLM-visible JSON Schema, excluding reserved context-bound parameters."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            if param.name in RESERVED_CONTEXT_PARAMS:
                continue
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def compute_pin_hash(self, tool_name: str) -> str:
        """Computes the deterministic SHA-256 schema pin hash (AU-57 compatible)."""
        return compute_mcp_schema_hash(
            name=tool_name,
            description=self.description,
            input_schema=self.to_json_schema(),
        )


class DbToolboxManifest(BaseModel):
    """Top-level manifest structure for db_tools.yaml."""

    sources: Dict[str, DbSourceConfig] = Field(default_factory=dict)
    tools: Dict[str, DbToolConfig] = Field(default_factory=dict)
    toolsets: Dict[str, List[str]] = Field(default_factory=dict)


class DbInspectSchemaInput(BaseModel):
    """Input schema for dynamic `db_inspect_schema` tool."""

    query: Optional[str] = Field(
        default=None,
        description="Optional natural-language intent or keyword to rank relevant tables.",
    )
    table_names: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific table names to inspect.",
    )
    include_indexes: bool = Field(
        default=True,
        description="Whether to include index definitions and comments in the M-Schema output.",
    )


class DbExecuteQueryInput(BaseModel):
    """Input schema for dynamic `db_execute_query` (SELECT) tool."""

    statement: Optional[str] = Field(
        default=None,
        description=(
            "Parameterized SQL SELECT statement using :param bind placeholders "
            "(e.g. 'SELECT id, title, next_due_at FROM reminders WHERE status = :status'). "
            "Never include DDL or mutation statements."
        ),
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dictionary of named bind parameter values matching :param placeholders.",
    )
    natural_language_query: Optional[str] = Field(
        default=None,
        description=(
            "Natural-language question or query intent. Used by the query planner if "
            "statement is omitted or requires self-correction."
        ),
    )


class DbMutateRecordsInput(BaseModel):
    """Input schema for dynamic `db_mutate_records` (INSERT, UPDATE, DELETE) tool."""

    operation: Literal["INSERT", "UPDATE", "DELETE"] = Field(
        description="DML mutation operation to perform: INSERT, UPDATE, or DELETE."
    )
    statement: Optional[str] = Field(
        default=None,
        description=(
            "Parameterized SQL INSERT, UPDATE, or DELETE statement using :param bind "
            "placeholders. UPDATE and DELETE must include an explicit WHERE filter."
        ),
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dictionary of named bind parameter values matching :param placeholders.",
    )
    natural_language_request: Optional[str] = Field(
        default=None,
        description=(
            "Natural-language description of the record insertion, update, or deletion "
            "for automatic M-Schema query planning or self-correction."
        ),
    )


def _detect_session_dialect(session: AsyncSession) -> str:
    """Detect the active SQLAlchemy engine dialect name from an AsyncSession."""
    bind = getattr(session, "bind", None)
    if bind is not None and hasattr(bind, "dialect"):
        return normalize_sqlglot_dialect(getattr(bind.dialect, "name", "sqlite"))
    try:
        sync_sess = getattr(session, "sync_session", None)
        if sync_sess is not None and getattr(sync_sess, "bind", None) is not None:
            return normalize_sqlglot_dialect(getattr(sync_sess.bind.dialect, "name", "sqlite"))
    except Exception:
        pass
    return "sqlite"


async def _resolve_and_ensure_profile_id(session: AsyncSession, raw_profile_id: str) -> str:
    """Resolves 'me' or 'default_profile' to the primary Profile ID, ensuring a Profile row exists."""
    clean_pid = (raw_profile_id or "").strip()
    if not clean_pid:
        raise ValueError(
            "Security invariant violation: profile_id is required in ToolContext. Fail-closed."
        )

    existing = (
        await session.execute(select(Profile).where(Profile.id == clean_pid))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id

    if clean_pid in ("me", "default_profile"):
        primary = (
            await session.execute(
                select(Profile)
                .order_by(Profile.is_primary.desc(), Profile.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if primary is not None:
            return primary.id

    stub = Profile(
        id=clean_pid,
        name="Primary Profile" if clean_pid in ("me", "default_profile") else clean_pid,
        relationship="self",
        role="self",
        is_primary=(clean_pid in ("me", "default_profile")),
        preferred_locale=DEFAULT_LOCALE,
    )
    session.add(stub)
    await session.flush()
    return clean_pid


def _run_coro_sync(coro: Any) -> Any:
    """Execute an async coroutine from a synchronous tool wrapper safely."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class McpDatabaseToolbox:
    """Multi-dialect declarative & dynamic MCP Database Toolbox."""

    def __init__(
        self,
        yaml_path: Optional[Path] = None,
        schema_catalog: Optional[SchemaCatalog] = None,
        model: Optional[BaseChatModel] = None,
        manifest: Optional[DbToolboxManifest] = None,
        manifest_path: Optional[Path] = None,
    ) -> None:
        self.yaml_path = manifest_path or yaml_path or DEFAULT_DB_TOOLS_YAML_PATH
        self.manifest_path = self.yaml_path
        self.schema_catalog = schema_catalog or get_schema_catalog()
        self.model = model
        self.manifest = manifest or self._load_manifest()

    @classmethod
    def from_yaml(cls, path: Optional[Path] = None) -> McpDatabaseToolbox:
        """Loads and validates `db_tools.yaml` into an `McpDatabaseToolbox` instance."""
        target_path = path or DEFAULT_DB_TOOLS_YAML_PATH
        return cls(yaml_path=target_path)

    def _load_manifest(self) -> DbToolboxManifest:
        if not self.yaml_path.exists():
            raise FileNotFoundError(
                f"MCP DB Toolbox configuration not found at {self.yaml_path}"
            )
        raw = yaml.safe_load(self.yaml_path.read_text(encoding="utf-8")) or {}
        base_manifest = DbToolboxManifest.model_validate(raw)

        for pack_yaml in _REGISTERED_PACK_YAML_PATHS:
            if pack_yaml.exists() and pack_yaml != self.yaml_path:
                try:
                    pack_raw = yaml.safe_load(pack_yaml.read_text(encoding="utf-8")) or {}
                    pack_manifest = DbToolboxManifest.model_validate(pack_raw)
                    base_manifest.sources.update(pack_manifest.sources)
                    base_manifest.tools.update(pack_manifest.tools)
                    for ts_name, ts_tools in pack_manifest.toolsets.items():
                        existing = base_manifest.toolsets.setdefault(ts_name, [])
                        for t in ts_tools:
                            if t not in existing:
                                existing.append(t)
                except Exception as exc:
                    logger.warning("Failed to merge pack db_tools.yaml %s: %s", pack_yaml, exc)

        return base_manifest

    def list_tool_names(self, toolset: Optional[str] = None) -> List[str]:
        """List declarative tool names, optionally filtered by toolset."""
        if toolset:
            resolved_ts = toolset
            if resolved_ts not in self.manifest.toolsets and resolved_ts.endswith("_assist_db"):
                resolved_ts = "assist_db"
            if resolved_ts not in self.manifest.toolsets:
                raise KeyError(f"Unknown DB toolset '{toolset}'")
            return list(self.manifest.toolsets[resolved_ts])
        return list(self.manifest.tools.keys())

    def get_toolset(self, toolset_name: str) -> List[str]:
        """Returns the list of tool names belonging to a named `toolset`."""
        resolved_ts = toolset_name
        if resolved_ts not in self.manifest.toolsets and resolved_ts.endswith("_assist_db"):
            resolved_ts = "assist_db"
        return list(self.manifest.toolsets.get(resolved_ts, []))

    def get_toolset_for_domain(self, domain: str, risk_class: str = "assist") -> List[str]:
        """Maps an agent's domain / risk_class to its authorized MCP DB toolset."""
        dom = (domain or "").strip().lower()
        rc = (risk_class or "").strip().lower()
        if dom == "navigation" or rc == "admin":
            base_tools = self.get_toolset("navigation_db")
        elif dom == "wellness" or rc == "wellness":
            base_tools = self.get_toolset("wellness_db")
        else:
            base_tools = self.get_toolset("assist_db")
        for dyn in ("db_inspect_schema", "db_execute_query", "db_mutate_records"):
            if dyn not in base_tools:
                base_tools.append(dyn)
        return base_tools

    def get_tool_definition(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Returns the OpenAI / LangChain tool definition dictionary for `bind_tools`."""
        if tool_name in self.manifest.tools:
            tool_cfg = self.manifest.tools[tool_name]
            return {
                "name": tool_name,
                "description": tool_cfg.description,
                "parameters": tool_cfg.to_json_schema(),
            }
        dyn_defs = self._get_dynamic_tool_definitions()
        return dyn_defs.get(tool_name)

    def _get_dynamic_tool_definitions(self) -> Dict[str, Dict[str, Any]]:
        return {
            "db_inspect_schema": {
                "name": "db_inspect_schema",
                "description": (
                    "Inspect the relational database schema, table comments, column types/comments, "
                    "foreign keys, and index comments formatted as M-Schema for query planning."
                ),
                "parameters": DbInspectSchemaInput.model_json_schema(),
            },
            "db_execute_query": {
                "name": "db_execute_query",
                "description": (
                    "Dynamically plan, AST-validate, and execute a parameterized SQL SELECT query "
                    "across any authorized table in the database. Strictly blocks DDL and mutations."
                ),
                "parameters": DbExecuteQueryInput.model_json_schema(),
            },
            "db_mutate_records": {
                "name": "db_mutate_records",
                "description": (
                    "Dynamically plan, AST-validate, and execute a parameterized SQL INSERT, UPDATE, "
                    "or DELETE statement on authorized profile tables. Strictly blocks DDL (CREATE, "
                    "ALTER, DROP, TRUNCATE) and requires an explicit WHERE clause on UPDATE/DELETE."
                ),
                "parameters": DbMutateRecordsInput.model_json_schema(),
            },
        }

    def get_all_tool_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Returns all declarative and dynamic DB tool definitions keyed by tool name."""
        defs = {
            name: {
                "name": name,
                "description": cfg.description,
                "parameters": cfg.to_json_schema(),
            }
            for name, cfg in self.manifest.tools.items()
        }
        defs.update(self._get_dynamic_tool_definitions())
        return defs

    def get_tool_config(self, name: str) -> DbToolConfig:
        """Return declarative DbToolConfig by tool name."""
        if name not in self.manifest.tools:
            raise KeyError(f"Unknown MCP DB tool '{name}'")
        return self.manifest.tools[name]

    def build_pydantic_args_schema(self, tool_name: str) -> type[BaseModel]:
        """Dynamically construct a Pydantic input model from the YAML parameter list."""
        cfg = self.get_tool_config(tool_name)
        type_map: Dict[str, Any] = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
        }
        field_definitions: Dict[str, Any] = {}
        for param in cfg.parameters:
            if param.name in RESERVED_CONTEXT_PARAMS:
                continue
            py_type = type_map.get(param.type, str)
            if param.required and param.default is None:
                field_definitions[param.name] = (
                    py_type,
                    Field(..., description=param.description),
                )
            else:
                field_definitions[param.name] = (
                    Optional[py_type],
                    Field(default=param.default, description=param.description),
                )

        model_name = (
            "".join(part.capitalize() for part in tool_name.split("_")) + "Input"
        )
        return create_model(model_name, **field_definitions)

    def inspect_schema(
        self,
        *,
        query: Optional[str] = None,
        table_names: Optional[Sequence[str]] = None,
        scope_ctx: Optional[Any] = None,
        dialect: str = "sqlite",
        include_indexes: bool = True,
    ) -> Dict[str, Any]:
        """Return structured schema metadata and M-Schema documentation for accessible tables."""
        norm_dialect = normalize_sqlglot_dialect(dialect)
        if table_names:
            selected_names = [
                t.strip().lower()
                for t in table_names
                if self.schema_catalog.is_table_accessible(t, scope_ctx=scope_ctx, mode="read")
            ]
        elif query and query.strip():
            selected_names = self.schema_catalog.prune_tables_for_intent(
                query, scope_ctx=scope_ctx, max_tables=8
            )
        else:
            selected_names = list(
                self.schema_catalog.get_accessible_tables(scope_ctx=scope_ctx, mode="read").keys()
            )

        m_schema = self.schema_catalog.get_m_schema(
            scope_ctx=scope_ctx,
            table_names=selected_names,
            dialect=norm_dialect,
            include_indexes=include_indexes,
        )
        tables_summary: List[Dict[str, Any]] = []
        for t_name in selected_names:
            t_doc = self.schema_catalog.get_table_doc(t_name, scope_ctx=scope_ctx, mode="read")
            if t_doc is not None:
                tables_summary.append(
                    {
                        "table": t_doc.name,
                        "comment": t_doc.comment,
                        "read_only": t_doc.read_only,
                        "domain_prefix": t_doc.domain_prefix,
                        "columns": [
                            {
                                "name": c.name,
                                "type": c.data_type,
                                "nullable": c.nullable,
                                "primary_key": c.primary_key,
                                "foreign_keys": c.foreign_keys,
                                "default": c.default,
                                "comment": c.comment,
                            }
                            for c in t_doc.columns.values()
                        ],
                        "indexes": [
                            {
                                "name": idx.name,
                                "columns": idx.columns,
                                "unique": idx.unique,
                                "comment": idx.comment,
                            }
                            for idx in t_doc.indexes
                        ],
                    }
                )

        return {
            "status": "ok",
            "tool": "db_inspect_schema",
            "dialect": norm_dialect,
            "table_count": len(tables_summary),
            "tables": tables_summary,
            "m_schema": m_schema,
        }

    async def execute_dynamic_query(
        self,
        *,
        statement: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        natural_language_query: Optional[str] = None,
        profile_id: str,
        user_id: Optional[str] = None,
        scope_ctx: Optional[Any] = None,
        session: Optional[AsyncSession] = None,
        model: Optional[BaseChatModel] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Plan, AST-validate, self-correct, and execute a dynamic SELECT query."""
        return await self._plan_validate_and_execute(
            allowed_operations=("SELECT",),
            operation_hint="SELECT",
            statement=statement,
            parameters=parameters,
            natural_language_request=natural_language_query,
            profile_id=profile_id,
            user_id=user_id,
            scope_ctx=scope_ctx,
            session=session,
            model=model or self.model,
            max_retries=max_retries,
        )

    async def execute_dynamic_mutation(
        self,
        *,
        operation: SqlOperation,
        statement: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        natural_language_request: Optional[str] = None,
        profile_id: str,
        user_id: Optional[str] = None,
        scope_ctx: Optional[Any] = None,
        session: Optional[AsyncSession] = None,
        model: Optional[BaseChatModel] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Plan, AST-validate, self-correct, and execute a dynamic INSERT, UPDATE, or DELETE statement."""
        op_upper = operation.strip().upper()
        if op_upper not in {"INSERT", "UPDATE", "DELETE"}:
            raise SqlSecurityError(
                f"Invalid mutation operation '{operation}'. Must be INSERT, UPDATE, or DELETE."
            )
        return await self._plan_validate_and_execute(
            allowed_operations=("INSERT", "UPDATE", "DELETE"),
            operation_hint=op_upper,  # type: ignore[arg-type]
            statement=statement,
            parameters=parameters,
            natural_language_request=natural_language_request,
            profile_id=profile_id,
            user_id=user_id,
            scope_ctx=scope_ctx,
            session=session,
            model=model or self.model,
            max_retries=max_retries,
        )

    async def _plan_validate_and_execute(
        self,
        *,
        allowed_operations: Sequence[SqlOperation],
        operation_hint: SqlOperation,
        statement: Optional[str],
        parameters: Optional[Dict[str, Any]],
        natural_language_request: Optional[str],
        profile_id: str,
        user_id: Optional[str],
        scope_ctx: Optional[Any],
        session: Optional[AsyncSession],
        model: Optional[BaseChatModel],
        max_retries: int,
    ) -> Dict[str, Any]:
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is strictly required for all dynamic DB operations.")

        if not statement and not natural_language_request:
            raise SqlValidationError(
                "Either a parameterized SQL 'statement' or a 'natural_language_query'/'natural_language_request' must be provided."
            )

        if session is not None:
            return await self._run_dynamic_in_session(
                session=session,
                allowed_operations=allowed_operations,
                operation_hint=operation_hint,
                statement=statement,
                parameters=parameters,
                natural_language_request=natural_language_request,
                profile_id=str(profile_id).strip(),
                user_id=user_id,
                scope_ctx=scope_ctx,
                model=model,
                max_retries=max_retries,
            )

        factory = get_session_factory()
        async with factory() as managed_session:
            return await self._run_dynamic_in_session(
                session=managed_session,
                allowed_operations=allowed_operations,
                operation_hint=operation_hint,
                statement=statement,
                parameters=parameters,
                natural_language_request=natural_language_request,
                profile_id=str(profile_id).strip(),
                user_id=user_id,
                scope_ctx=scope_ctx,
                model=model,
                max_retries=max_retries,
            )

    async def _run_dynamic_in_session(
        self,
        *,
        session: AsyncSession,
        allowed_operations: Sequence[SqlOperation],
        operation_hint: SqlOperation,
        statement: Optional[str],
        parameters: Optional[Dict[str, Any]],
        natural_language_request: Optional[str],
        profile_id: str,
        user_id: Optional[str],
        scope_ctx: Optional[Any],
        model: Optional[BaseChatModel],
        max_retries: int,
    ) -> Dict[str, Any]:
        resolved_profile_id = await _resolve_and_ensure_profile_id(session, profile_id)
        target_dialect = _detect_session_dialect(session)
        planner = DbQueryPlanner(model=model, schema_catalog=self.schema_catalog)

        effective_scope_ctx = scope_ctx
        if effective_scope_ctx is None:
            effective_scope_ctx = ScopeContext(
                profile_id=resolved_profile_id,
                scope=DEFAULT_SCOPE,
                actor=user_id,
            )

        current_sql = statement
        current_params = dict(parameters or {})
        rationale = "Direct parameterized SQL execution."
        last_error: Optional[str] = None
        attempts = 0

        while attempts <= max_retries:
            attempts += 1
            if not current_sql or last_error is not None:
                plan_req = natural_language_request or statement or ""
                plan: SqlQueryPlan = await planner.plan_query(
                    plan_req,
                    operation_hint=operation_hint,
                    parameters=current_params,
                    scope_ctx=effective_scope_ctx,
                    dialect=target_dialect,
                    previous_error=last_error,
                    previous_sql=current_sql,
                )
                current_sql = plan.statement
                current_params = plan.parameters
                rationale = plan.rationale

            try:
                validated: ValidatedSqlPlan = validate_and_rewrite_sql(
                    current_sql or "",
                    current_params,
                    profile_id=resolved_profile_id,
                    scope_ctx=effective_scope_ctx,
                    schema_catalog=self.schema_catalog,
                    source_dialect=target_dialect,
                    target_dialect=target_dialect,
                    allowed_operations=allowed_operations,
                )

                if validated.operation == "SELECT" and target_dialect == "sqlite":
                    await session.execute(
                        text(f"EXPLAIN QUERY PLAN {validated.rewritten_sql}"),
                        validated.bound_params,
                    )

                result = await session.execute(
                    text(validated.rewritten_sql),
                    validated.bound_params,
                )

                if validated.operation == "SELECT":
                    rows = [dict(r) for r in result.mappings().all()]
                    return {
                        "status": "ok",
                        "tool": "db_execute_query",
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

                affected = (
                    result.rowcount
                    if result.rowcount is not None and result.rowcount >= 0
                    else 0
                )
                returned_rows: List[Dict[str, Any]] = []
                if result.returns_rows:
                    returned_rows = [dict(r) for r in result.mappings().all()]
                    affected = max(affected, len(returned_rows))

                await session.commit()

                if "notes" in validated.target_tables:
                    await self._invalidate_note_search_index(
                        resolved_profile_id, validated.bound_params.get("__ctx_id")
                    )

                return {
                    "status": "ok",
                    "tool": "db_mutate_records",
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

            except SqlSecurityError:
                raise
            except (SqlValidationError, Exception) as exc:
                last_error = str(exc)
                if attempts > max_retries:
                    if isinstance(exc, SqlValidationError):
                        raise
                    raise SqlValidationError(
                        f"Dynamic SQL execution failed after {attempts} attempt(s): {last_error}"
                    ) from exc
                logger.info(
                    "Self-correcting dynamic SQL plan (attempt %d/%d) after validation error: %s",
                    attempts,
                    max_retries + 1,
                    last_error,
                )

        raise SqlValidationError(f"Dynamic SQL execution failed: {last_error}")

    async def execute_tool(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]],
        ctx: Any = None,
    ) -> Dict[str, Any]:
        """Executes a declarative or dynamic SQL tool with strict context-bound `:profile_id` isolation."""
        if ctx is None:
            raise ValueError(
                "Security invariant violation: ToolContext is required for database tools. Fail-closed."
            )

        raw_profile_id = getattr(ctx, "profile_id", None)
        if raw_profile_id is None or not str(raw_profile_id).strip():
            raise ValueError(
                "Security invariant violation: profile_id is required in ToolContext. Fail-closed."
            )

        user_id = getattr(ctx, "user_id", None)
        scope = getattr(ctx, "scope", None) or DEFAULT_SCOPE
        safe_args = dict(args or {})
        for reserved_key in RESERVED_CONTEXT_PARAMS:
            safe_args.pop(reserved_key, None)

        return await self.execute(
            tool_name,
            safe_args,
            profile_id=str(raw_profile_id).strip(),
            user_id=user_id,
            scope=scope,
        )

    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        profile_id: str,
        user_id: Optional[str] = None,
        scope: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Execute a registered MCP DB tool inside a profile-isolated database session."""
        if not profile_id or not str(profile_id).strip():
            raise ValueError("profile_id is strictly required for all MCP DB tool executions.")

        if tool_name == "db_inspect_schema":
            scope_ctx = (
                ScopeContext(
                    profile_id=str(profile_id).strip(),
                    scope=scope or DEFAULT_SCOPE,
                    actor=user_id,
                    granted_scopes=frozenset({scope or DEFAULT_SCOPE, f"{(scope or DEFAULT_SCOPE).split('.')[0]}.*"}),
                )
                if scope
                else None
            )
            return self.inspect_schema(
                query=params.get("query"),
                table_names=params.get("table_names"),
                scope_ctx=scope_ctx,
                include_indexes=bool(params.get("include_indexes", True)),
            )

        if tool_name == "db_execute_query":
            scope_ctx = (
                ScopeContext(
                    profile_id=str(profile_id).strip(),
                    scope=scope or DEFAULT_SCOPE,
                    actor=user_id,
                    granted_scopes=frozenset({scope or DEFAULT_SCOPE, f"{(scope or DEFAULT_SCOPE).split('.')[0]}.*"}),
                )
                if scope
                else None
            )
            return await self.execute_dynamic_query(
                statement=params.get("statement"),
                parameters=params.get("parameters"),
                natural_language_query=params.get("natural_language_query"),
                profile_id=str(profile_id).strip(),
                user_id=user_id,
                scope_ctx=scope_ctx,
                session=session,
            )

        if tool_name == "db_mutate_records":
            scope_ctx = (
                ScopeContext(
                    profile_id=str(profile_id).strip(),
                    scope=scope or DEFAULT_SCOPE,
                    actor=user_id,
                    granted_scopes=frozenset({scope or DEFAULT_SCOPE, f"{(scope or DEFAULT_SCOPE).split('.')[0]}.*"}),
                )
                if scope
                else None
            )
            return await self.execute_dynamic_mutation(
                operation=params.get("operation", "INSERT"),
                statement=params.get("statement"),
                parameters=params.get("parameters"),
                natural_language_request=params.get("natural_language_request"),
                profile_id=str(profile_id).strip(),
                user_id=user_id,
                scope_ctx=scope_ctx,
                session=session,
            )

        cfg = self.get_tool_config(tool_name)
        args_model = self.build_pydantic_args_schema(tool_name)
        validated = args_model.model_validate(params)
        clean_params = validated.model_dump()

        for p in cfg.parameters:
            if clean_params.get(p.name) is None and p.default is not None:
                clean_params[p.name] = p.default
            if isinstance(clean_params.get(p.name), str):
                clean_params[p.name] = normalize_text_nfc(clean_params[p.name])

        now_iso = datetime.now(timezone.utc).isoformat()
        exec_params: Dict[str, Any] = {
            **clean_params,
            "profile_id": str(profile_id).strip(),
            "user_id": user_id,
            "scope": scope or DEFAULT_SCOPE,
            "now": now_iso,
        }
        exec_params.setdefault("id", str(uuid.uuid4()))

        if session is not None:
            return await self._execute_in_session(session, tool_name, cfg, exec_params)

        factory = get_session_factory()
        async with factory() as managed_session:
            return await self._execute_in_session(
                managed_session, tool_name, cfg, exec_params
            )

    async def _execute_in_session(
        self,
        session: AsyncSession,
        tool_name: str,
        cfg: DbToolConfig,
        exec_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the parameterized SQL statement (or registered domain hook) in session."""
        exec_params["profile_id"] = await _resolve_and_ensure_profile_id(
            session, str(exec_params["profile_id"])
        )

        if tool_name in _REGISTERED_TOOL_HOOKS:
            hook_res = await _REGISTERED_TOOL_HOOKS[tool_name](
                tool_name,
                exec_params,
                exec_params.get("profile_id"),
                exec_params.get("user_id"),
                session,
            )
            if hook_res is not None:
                return hook_res

        if tool_name == "upsert_workspace_note":
            active_scope = str(exec_params.get("scope") or DEFAULT_SCOPE)
            with scope_context(
                scope=active_scope,
                profile_id=str(exec_params["profile_id"]),
                actor=exec_params.get("user_id"),
            ):
                return await self._handle_upsert_workspace_note(
                    session, tool_name, cfg, exec_params
                )

        if tool_name == "create_profile_reminder":
            return await self._handle_create_profile_reminder(session, tool_name, cfg, exec_params)

        sql_to_run = self._adapt_sql_for_session_dialect(cfg.statement, session)
        stmt = text(sql_to_run)
        result = await session.execute(stmt, exec_params)

        is_write = cfg.risk_tier != "read"
        if result.returns_rows:
            rows = [dict(r) for r in result.mappings().all()]
        else:
            rows = []

        if is_write:
            await session.commit()

        if cfg.risk_tier == "read":
            return {
                "status": "ok",
                "tool": tool_name,
                "entity": cfg.entity,
                "count": len(rows),
                "records": rows,
            }

        return {
            "status": "ok",
            "tool": tool_name,
            "entity": cfg.entity,
            "record": rows[0] if rows else {"id": exec_params["id"]},
        }

    def _adapt_sql_for_session_dialect(self, sql: str, session: AsyncSession) -> str:
        """Transpile declarative SQL statement if the active session dialect is not SQLite."""
        target_dialect = _detect_session_dialect(session)
        if target_dialect == "sqlite":
            return sql
        try:
            transpiled_list = sqlglot.transpile(sql, read="sqlite", write=target_dialect)
            if transpiled_list:
                from yarvelle_core.tools.sql_ast_sandbox import _normalize_sqlalchemy_placeholders

                return _normalize_sqlalchemy_placeholders(transpiled_list[0])
        except Exception as exc:
            logger.debug("SQL dialect adaptation fallback for %s: %s", target_dialect, exc)
        return sql

    async def _handle_upsert_workspace_note(
        self,
        session: AsyncSession,
        tool_name: str,
        cfg: DbToolConfig,
        exec_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        slug = str(exec_params.get("slug", "")).strip()
        profile_id = str(exec_params["profile_id"])
        active_scope = str(exec_params.get("scope") or DEFAULT_SCOPE)

        existing = await session.execute(
            text(
                "SELECT id FROM notes WHERE profile_id = :profile_id AND slug = :slug LIMIT 1"
            ),
            {"profile_id": profile_id, "slug": slug},
        )
        existing_row = existing.mappings().first()
        if existing_row and existing_row.get("id"):
            exec_params["id"] = str(existing_row["id"])

        tags_raw = exec_params.get("tags_json", "[]")
        try:
            parsed_tags = (
                json.loads(tags_raw) if isinstance(tags_raw, str) else list(tags_raw)
            )
            if not isinstance(parsed_tags, list):
                parsed_tags = [str(parsed_tags)]
        except Exception:
            parsed_tags = [
                t.strip() for t in str(tags_raw).split(",") if t.strip()
            ]
        exec_params["tags_json"] = json.dumps(parsed_tags)

        raw_locale = exec_params.get("locale") or DEFAULT_LOCALE
        try:
            exec_params["locale"] = canonicalize_locale(str(raw_locale))
        except Exception:
            exec_params["locale"] = DEFAULT_LOCALE

        linked_appt = exec_params.get("linked_appointment_id")
        exec_params["linked_appointment_id"] = (
            str(linked_appt).strip() if linked_appt and str(linked_appt).strip() else None
        )

        now_dt = datetime.now(timezone.utc)
        existing_note = await session.get(Note, exec_params["id"])
        if existing_note is not None:
            existing_note.type = exec_params.get("type", "scratchpad")
            existing_note.title = exec_params["title"]
            existing_note.content = exec_params["content"]
            existing_note.tags_json = exec_params["tags_json"]
            existing_note.locale = exec_params["locale"]
            existing_note.linked_appointment_id = exec_params["linked_appointment_id"]
            existing_note.updated_at = now_dt
            note_obj = existing_note
        else:
            note_obj = Note(
                id=exec_params["id"],
                type=exec_params.get("type", "scratchpad"),
                user_id=exec_params.get("user_id"),
                profile_id=profile_id,
                scope=active_scope,
                slug=slug,
                title=exec_params["title"],
                content=exec_params["content"],
                tags_json=exec_params["tags_json"],
                locale=exec_params["locale"],
                linked_appointment_id=exec_params["linked_appointment_id"],
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(note_obj)

        await session.commit()
        await self._invalidate_note_search_index(profile_id, note_obj.id)

        return {
            "status": "ok",
            "tool": tool_name,
            "entity": cfg.entity,
            "record": {
                "id": note_obj.id,
                "slug": note_obj.slug,
                "title": note_obj.title,
                "type": note_obj.type,
                "scope": note_obj.scope,
                "profile_id": note_obj.profile_id,
                "locale": note_obj.locale,
                "linked_appointment_id": note_obj.linked_appointment_id,
                "updated_at": (
                    note_obj.updated_at.isoformat()
                    if note_obj.updated_at
                    else exec_params["now"]
                ),
            },
        }

    async def _handle_create_profile_reminder(
        self,
        session: AsyncSession,
        tool_name: str,
        cfg: DbToolConfig,
        exec_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_due = str(exec_params.get("next_due_at", "")).strip()
        try:
            due_dt = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ValueError(
                f"Invalid ISO-8601 timestamp for next_due_at: '{raw_due}'."
            ) from exc

        exec_params["next_due_at"] = due_dt.isoformat()
        exec_params["rrule"] = exec_params.get("rrule") or None
        exec_params["description"] = exec_params.get("description") or None

        sql_to_run = self._adapt_sql_for_session_dialect(cfg.statement, session)
        result = await session.execute(text(sql_to_run), exec_params)
        rows = [dict(r) for r in result.mappings().all()] if result.returns_rows else []

        job = Job(
            id=str(uuid.uuid4()),
            profile_id=exec_params["profile_id"],
            scope=str(exec_params.get("scope") or DEFAULT_SCOPE),
            kind="reminder",
            payload={
                "reminder_id": exec_params["id"],
                "title": exec_params["title"],
                "category": exec_params.get("category", "general"),
            },
            timezone=exec_params.get("timezone", "UTC"),
            rrule=exec_params.get("rrule"),
            next_run_at=due_dt,
            idempotency_key=f"reminder:{exec_params['id']}:{due_dt.isoformat()}",
            status="pending",
        )
        session.add(job)
        await session.commit()

        return {
            "status": "ok",
            "tool": tool_name,
            "entity": cfg.entity,
            "record": rows[0] if rows else {"id": exec_params["id"]},
            "scheduled_job_id": job.id,
        }

    async def _invalidate_note_search_index(
        self,
        profile_id: str,
        note_id: Optional[str] = None,
    ) -> None:
        try:
            from yarvelle_core.search import get_search_index

            idx = get_search_index()
            if idx is not None and note_id:
                await idx.invalidate(profile_id, "note", str(note_id))
        except Exception as exc:
            logger.debug("Search index invalidation after note mutation skipped: %s", exc)

    def to_tool_specs(self) -> List[ToolSpec]:
        """Converts all declarative and dynamic tools into Yarvelle Core `ToolSpec` instances."""
        specs: List[ToolSpec] = []
        for tool_name, tool_cfg in self.manifest.tools.items():

            def _make_executor(t_name: str):
                async def _executor(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
                    return await self.execute_tool(t_name, args, ctx)

                return _executor

            spec = ToolSpec(
                name=tool_name,
                description=tool_cfg.description,
                parameters=tool_cfg.to_json_schema(),
                risk_tier=tool_cfg.risk_tier,
                trust="trusted",
                data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
                executor=_make_executor(tool_name),
                metadata={
                    "source": "mcp_db_toolbox",
                    "entity": tool_cfg.entity,
                    "risk": tool_cfg.risk_tier,
                    "schema_hash": tool_cfg.compute_pin_hash(tool_name),
                    "undoable": tool_cfg.risk_tier == "write_local",
                },
            )
            specs.append(spec)

        # Register the 3 dynamic AST-sandboxed tools as ToolSpecs as well
        dyn_defs = self._get_dynamic_tool_definitions()
        dyn_tiers: Dict[str, RiskTier] = {
            "db_inspect_schema": "read",
            "db_execute_query": "read",
            "db_mutate_records": "write_local",
        }
        for dyn_name, dyn_def in dyn_defs.items():

            def _make_dyn_executor(d_name: str):
                async def _dyn_executor(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
                    return await self.execute_tool(d_name, args, ctx)

                return _dyn_executor

            r_tier = dyn_tiers[dyn_name]
            specs.append(
                ToolSpec(
                    name=dyn_name,
                    description=dyn_def["description"],
                    parameters=dyn_def["parameters"],
                    risk_tier=r_tier,
                    trust="trusted",
                    data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
                    executor=_make_dyn_executor(dyn_name),
                    metadata={
                        "source": "mcp_db_toolbox",
                        "entity": "dynamic_sql",
                        "risk": r_tier,
                        "dynamic_sql": True,
                        "undoable": r_tier == "write_local",
                    },
                )
            )
        return specs

    def build_dynamic_langchain_tools(
        self,
        *,
        profile_id: str,
        user_id: Optional[str] = None,
        scope_ctx: Optional[Any] = None,
        session: Optional[AsyncSession] = None,
        model: Optional[BaseChatModel] = None,
    ) -> List[BaseTool]:
        """Build the 3 dynamic AST-sandboxed database tools (`db_inspect_schema`, `db_execute_query`, `db_mutate_records`)."""
        toolbox = self
        active_scope = (
            getattr(scope_ctx, "scope", None) if scope_ctx is not None else DEFAULT_SCOPE
        )
        effective_ctx = scope_ctx or ScopeContext(
            profile_id=profile_id,
            scope=active_scope or DEFAULT_SCOPE,
            actor=user_id,
            granted_scopes=frozenset(
                {active_scope or DEFAULT_SCOPE, f"{(active_scope or DEFAULT_SCOPE).split('.')[0]}.*"}
            ),
        )

        async def _inspect_coro(
            query: Optional[str] = None,
            table_names: Optional[List[str]] = None,
            include_indexes: bool = True,
        ) -> str:
            dialect = _detect_session_dialect(session) if session is not None else "sqlite"
            res = toolbox.inspect_schema(
                query=query,
                table_names=table_names,
                scope_ctx=effective_ctx,
                dialect=dialect,
                include_indexes=include_indexes,
            )
            return json.dumps(res, default=str)

        def _inspect_sync(
            query: Optional[str] = None,
            table_names: Optional[List[str]] = None,
            include_indexes: bool = True,
        ) -> str:
            return _run_coro_sync(
                _inspect_coro(
                    query=query,
                    table_names=table_names,
                    include_indexes=include_indexes,
                )
            )

        inspect_tool = StructuredTool.from_function(
            func=_inspect_sync,
            coroutine=_inspect_coro,
            name="db_inspect_schema",
            description=(
                "Inspect the relational database schema, table comments, column types/comments, "
                "foreign keys, and index comments formatted as M-Schema for query planning."
            ),
            args_schema=DbInspectSchemaInput,
        )
        inspect_tool.metadata = {
            "risk_tier": "read",
            "entity": "schema",
            "source": "yarvelle-db",
            "mcp_db_tool": True,
            "dynamic_sql": True,
        }

        async def _query_coro(
            statement: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            natural_language_query: Optional[str] = None,
        ) -> str:
            res = await toolbox.execute_dynamic_query(
                statement=statement,
                parameters=parameters,
                natural_language_query=natural_language_query,
                profile_id=profile_id,
                user_id=user_id,
                scope_ctx=effective_ctx,
                session=session,
                model=model,
            )
            return json.dumps(res, default=str)

        def _query_sync(
            statement: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            natural_language_query: Optional[str] = None,
        ) -> str:
            return _run_coro_sync(
                _query_coro(
                    statement=statement,
                    parameters=parameters,
                    natural_language_query=natural_language_query,
                )
            )

        query_tool = StructuredTool.from_function(
            func=_query_sync,
            coroutine=_query_coro,
            name="db_execute_query",
            description=(
                "Dynamically plan, AST-validate, and execute a parameterized SQL SELECT query "
                "across any authorized table in the database. Strictly blocks DDL and mutations."
            ),
            args_schema=DbExecuteQueryInput,
        )
        query_tool.metadata = {
            "risk_tier": "read",
            "entity": "query",
            "source": "yarvelle-db",
            "mcp_db_tool": True,
            "dynamic_sql": True,
        }

        async def _mutate_coro(
            operation: Literal["INSERT", "UPDATE", "DELETE"],
            statement: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            natural_language_request: Optional[str] = None,
        ) -> str:
            res = await toolbox.execute_dynamic_mutation(
                operation=operation,
                statement=statement,
                parameters=parameters,
                natural_language_request=natural_language_request,
                profile_id=profile_id,
                user_id=user_id,
                scope_ctx=effective_ctx,
                session=session,
                model=model,
            )
            return json.dumps(res, default=str)

        def _mutate_sync(
            operation: Literal["INSERT", "UPDATE", "DELETE"],
            statement: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            natural_language_request: Optional[str] = None,
        ) -> str:
            return _run_coro_sync(
                _mutate_coro(
                    operation=operation,
                    statement=statement,
                    parameters=parameters,
                    natural_language_request=natural_language_request,
                )
            )

        mutate_tool = StructuredTool.from_function(
            func=_mutate_sync,
            coroutine=_mutate_coro,
            name="db_mutate_records",
            description=(
                "Dynamically plan, AST-validate, and execute a parameterized SQL INSERT, UPDATE, "
                "or DELETE statement on authorized profile tables. Strictly blocks DDL (CREATE, "
                "ALTER, DROP, TRUNCATE) and requires an explicit WHERE clause on UPDATE/DELETE."
            ),
            args_schema=DbMutateRecordsInput,
        )
        mutate_tool.metadata = {
            "risk_tier": "write_local",
            "entity": "mutation",
            "source": "yarvelle-db",
            "mcp_db_tool": True,
            "dynamic_sql": True,
        }

        return [inspect_tool, query_tool, mutate_tool]

    def build_langchain_tools(
        self,
        *,
        profile_id: str,
        user_id: Optional[str] = None,
        scope_ctx: Optional[Any] = None,
        tool_names: Optional[Sequence[str]] = None,
        toolset: Optional[str] = None,
        session: Optional[AsyncSession] = None,
        include_dynamic_tools: bool = True,
        model: Optional[BaseChatModel] = None,
    ) -> List[BaseTool]:
        """Build LangChain StructuredTools bound to a specific profile_id and ScopeContext."""
        if tool_names is not None:
            names = [n for n in tool_names if n in self.manifest.tools]
        else:
            names = self.list_tool_names(toolset=toolset)

        active_scope = (
            getattr(scope_ctx, "scope", None) if scope_ctx is not None else DEFAULT_SCOPE
        )
        lc_tools: List[BaseTool] = []
        for name in names:
            cfg = self.get_tool_config(name)
            args_schema = self.build_pydantic_args_schema(name)
            lc_tools.append(
                self._make_structured_tool(
                    tool_name=name,
                    cfg=cfg,
                    args_schema=args_schema,
                    profile_id=profile_id,
                    user_id=user_id,
                    scope=active_scope,
                    session=session,
                )
            )

        should_add_dynamic = include_dynamic_tools or (
            tool_names is not None and bool(set(tool_names) & DYNAMIC_DB_TOOL_NAMES)
        )
        if should_add_dynamic:
            dyn_tools = self.build_dynamic_langchain_tools(
                profile_id=profile_id,
                user_id=user_id,
                scope_ctx=scope_ctx,
                session=session,
                model=model,
            )
            for dt in dyn_tools:
                if tool_names is None or include_dynamic_tools or dt.name in tool_names:
                    lc_tools.append(dt)

        return lc_tools

    def _make_structured_tool(
        self,
        *,
        tool_name: str,
        cfg: DbToolConfig,
        args_schema: type[BaseModel],
        profile_id: str,
        user_id: Optional[str],
        scope: Optional[str],
        session: Optional[AsyncSession],
    ) -> StructuredTool:
        toolbox = self

        async def _arun(**kwargs: Any) -> str:
            res = await toolbox.execute(
                tool_name,
                kwargs,
                profile_id=profile_id,
                user_id=user_id,
                scope=scope,
                session=session,
            )
            return json.dumps(res, default=str)

        def _run(**kwargs: Any) -> str:
            return _run_coro_sync(_arun(**kwargs))

        tool = StructuredTool.from_function(
            func=_run,
            coroutine=_arun,
            name=tool_name,
            description=cfg.description,
            args_schema=args_schema,
        )
        tool.metadata = {
            "risk_tier": cfg.risk_tier,
            "entity": cfg.entity,
            "source": cfg.source,
            "mcp_db_tool": True,
        }
        return tool


_DEFAULT_TOOLBOX: Optional[McpDatabaseToolbox] = None


def get_mcp_db_toolbox(path: Optional[Path] = None) -> McpDatabaseToolbox:
    """Return the singleton McpDatabaseToolbox instance."""
    global _DEFAULT_TOOLBOX
    if path is not None:
        return McpDatabaseToolbox.from_yaml(path)
    if _DEFAULT_TOOLBOX is None:
        _DEFAULT_TOOLBOX = McpDatabaseToolbox()
    return _DEFAULT_TOOLBOX


# Backward-compatible function alias used across engine and agent nodes
get_db_toolbox = get_mcp_db_toolbox


def register_db_toolbox_specs(registry: ToolSpecRegistry) -> ToolSpecRegistry:
    """Registers all declarative and dynamic MCP DB ToolSpecs into a `ToolSpecRegistry`."""
    toolbox = get_db_toolbox()
    for spec in toolbox.to_tool_specs():
        registry.register(spec)
    return registry


def get_db_tools_for_agent(
    agent_id: str,
    risk_class: Optional[str] = None,
    requested_tool_names: Optional[Sequence[str]] = None,
    *,
    profile_id: Optional[str] = None,
    user_id: Optional[str] = None,
    scope_ctx: Optional[Any] = None,
    session: Optional[AsyncSession] = None,
    model: Optional[BaseChatModel] = None,
) -> List[BaseTool]:
    """Provision declarative and dynamic MCP DB tools for an agent."""
    if not profile_id:
        return []

    toolbox = get_mcp_db_toolbox()

    if requested_tool_names:
        explicit_db_tools = [
            t
            for t in requested_tool_names
            if t in toolbox.manifest.tools or t in DYNAMIC_DB_TOOL_NAMES
        ]
        if explicit_db_tools:
            return toolbox.build_langchain_tools(
                profile_id=profile_id,
                user_id=user_id,
                scope_ctx=scope_ctx,
                tool_names=explicit_db_tools,
                session=session,
                include_dynamic_tools=bool(set(explicit_db_tools) & DYNAMIC_DB_TOOL_NAMES),
                model=model,
            )

    if agent_id == "db-operator":
        return toolbox.build_langchain_tools(
            profile_id=profile_id,
            user_id=user_id,
            scope_ctx=scope_ctx,
            toolset="all_db_tools",
            session=session,
            include_dynamic_tools=True,
            model=model,
        )

    rc = (risk_class or "").lower().strip()
    toolset_map = {
        "assist": "assist_db",
        "admin": "navigation_db",
        "wellness": "wellness_db",
    }
    toolset = toolset_map.get(rc, "core_db")
    return toolbox.build_langchain_tools(
        profile_id=profile_id,
        user_id=user_id,
        scope_ctx=scope_ctx,
        toolset=toolset,
        session=session,
        include_dynamic_tools=True,
        model=model,
    )


__all__ = [
    "DEFAULT_DB_TOOLS_YAML_PATH",
    "DYNAMIC_DB_TOOL_NAMES",
    "DbExecuteQueryInput",
    "DbInspectSchemaInput",
    "DbMutateRecordsInput",
    "DbParameterSpec",
    "DbSourceConfig",
    "DbToolConfig",
    "DbToolParameter",
    "DbToolboxManifest",
    "McpDatabaseToolbox",
    "RESERVED_CONTEXT_PARAMS",
    "get_db_toolbox",
    "get_db_tools_for_agent",
    "get_mcp_db_toolbox",
    "register_db_tool_hook",
    "register_db_tools_yaml",
    "register_db_toolbox_specs",
]
