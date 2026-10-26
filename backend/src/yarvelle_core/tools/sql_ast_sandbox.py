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

"""Deterministic SQL AST Firewall, Tenant/Scope Rewriter, and Dialect Transpiler.

Enforces a 5-stage security pipeline on all dynamic SQL operations using sqlglot:
1. Single-statement parse (blocks stacked queries and comment injection).
2. Strict DQL/DML statement allowlist (allows only SELECT, INSERT, UPDATE, DELETE;
   blocks all DDL, DCL, TCL, engine admin commands, writable CTEs in SELECT, and
   dangerous system functions).
3. Table & column verification against SchemaCatalog, SYSTEM_DENYLIST_TABLES,
   READ_ONLY_TABLES, and ScopeContext authorization.
4. Mandatory AST-level tenant (profile_id) and domain scope (scope) predicate
   injection, immutable column protection, and bounded LIMIT enforcement.
5. Parameterization verification and multi-dialect SQL transpilation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, FrozenSet, Iterable, List, Literal, Optional, Set
import uuid

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from yarvelle_core.db.schema_catalog import (
    IMMUTABLE_COLUMNS,
    READ_ONLY_TABLES,
    SYSTEM_DENYLIST_TABLES,
    SchemaCatalog,
    TableSchemaDoc,
    get_schema_catalog,
)

SqlOperation = Literal["SELECT", "INSERT", "UPDATE", "DELETE"]
RiskTierLiteral = Literal["read", "write_local", "write_external", "irreversible"]

DEFAULT_SELECT_LIMIT = 100
MAX_SELECT_LIMIT = 500

# Forbidden SQL statement start keywords (defense-in-depth pre-parse gate)
FORBIDDEN_LEADING_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
        "RENAME",
        "GRANT",
        "REVOKE",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "BEGIN",
        "START",
        "PRAGMA",
        "ATTACH",
        "DETACH",
        "VACUUM",
        "ANALYZE",
        "REINDEX",
        "COPY",
        "LOAD",
        "SET",
        "RESET",
        "SHOW",
        "USE",
        "EXPLAIN",
        "EXEC",
        "EXECUTE",
        "CALL",
        "MERGE",
        "REPLACE",
    }
)

# Forbidden internal/system schemas and catalog tables across SQLite, Postgres, MySQL, MSSQL
FORBIDDEN_SYSTEM_IDENTIFIERS: FrozenSet[str] = frozenset(
    {
        "sqlite_master",
        "sqlite_schema",
        "sqlite_temp_master",
        "sqlite_temp_schema",
        "sqlite_sequence",
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "pg_temp",
        "pg_stat_activity",
        "pg_shadow",
        "pg_authid",
        "pg_roles",
        "pg_user",
        "mysql",
        "performance_schema",
        "sys",
        "msdb",
        "master",
        "tempdb",
    }
)

# Dangerous or side-effecting SQL functions blocked in any expression
FORBIDDEN_SQL_FUNCTIONS: FrozenSet[str] = frozenset(
    {
        "load_extension",
        "fts3_tokenizer",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_sleep",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "lo_import",
        "lo_export",
        "randomblob",
        "zeroblob",
        "current_setting",
        "set_config",
        "xp_cmdshell",
        "openrowset",
        "opendatasource",
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
    }
)

# AST node types that are strictly forbidden anywhere inside a query tree
FORBIDDEN_AST_NODE_TYPES: tuple[type[exp.Expression], ...] = tuple(
    cls
    for cls in (
        getattr(exp, "Create", None),
        getattr(exp, "Alter", None),
        getattr(exp, "Drop", None),
        getattr(exp, "TruncateTable", None),
        getattr(exp, "Command", None),
        getattr(exp, "Grant", None),
        getattr(exp, "Revoke", None),
        getattr(exp, "Commit", None),
        getattr(exp, "Rollback", None),
        getattr(exp, "Transaction", None),
        getattr(exp, "Pragma", None),
        getattr(exp, "Use", None),
        getattr(exp, "Set", None),
        getattr(exp, "Show", None),
        getattr(exp, "LoadData", None),
        getattr(exp, "Copy", None),
        getattr(exp, "Analyze", None),
        getattr(exp, "Merge", None),
        getattr(exp, "Attach", None),
        getattr(exp, "Detach", None),
    )
    if cls is not None
)

DIALECT_NORMALIZATION_MAP: Dict[str, str] = {
    "sql": "sqlite",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "aiosqlite": "sqlite",
    "postgres": "postgres",
    "postgresql": "postgres",
    "asyncpg": "postgres",
    "psycopg": "postgres",
    "psycopg2": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "aiomysql": "mysql",
    "asyncmy": "mysql",
    "mssql": "tsql",
    "tsql": "tsql",
    "sqlserver": "tsql",
    "aioodbc": "tsql",
    "duckdb": "duckdb",
}


class SqlSecurityError(PermissionError):
    """Raised when a SQL statement violates DDL/DCL/TCL, table, or scope security invariants."""


class SqlValidationError(ValueError):
    """Raised when a SQL statement has syntax errors or references non-existent tables/columns."""


@dataclass
class ValidatedSqlPlan:
    """Result of deterministic AST validation, tenant/scope injection, and dialect transpilation."""

    operation: SqlOperation
    risk_tier: RiskTierLiteral
    target_tables: List[str]
    rewritten_sql: str
    bound_params: Dict[str, Any] = field(default_factory=dict)
    dialect: str = "sqlite"
    original_sql: str = ""


def normalize_sqlglot_dialect(dialect: Optional[str]) -> str:
    """Normalize a SQLAlchemy or config dialect string to a sqlglot dialect name."""
    if not dialect:
        return "sqlite"
    cleaned = dialect.strip().lower().split("+", 1)[0]
    return DIALECT_NORMALIZATION_MAP.get(cleaned, "sqlite")


def _normalize_sqlalchemy_placeholders(sql: str) -> str:
    """Ensure rendered SQL uses colon-prefixed `:param` placeholders for SQLAlchemy text()."""
    # Convert psycopg-style %(param)s to :param
    converted = re.sub(r"%\(([a-zA-Z_][a-zA-Z0-9_]*)\)s", r":\1", sql)
    # Convert duckdb-style $param to :param (avoiding $1 positional or string literals)
    converted = re.sub(r"(?<![a-zA-Z0-9_])\$([a-zA-Z_][a-zA-Z0-9_]*)", r":\1", converted)
    return converted


def _is_tautology(expr: Optional[exp.Expression]) -> bool:
    """Return True if an expression is a trivial boolean tautology (e.g. 1=1, 'a'='a', TRUE)."""
    if expr is None:
        return True
    if isinstance(expr, exp.Paren):
        return _is_tautology(expr.this)
    if isinstance(expr, exp.Boolean):
        return bool(expr.this)
    if isinstance(expr, exp.Literal):
        return True
    if isinstance(expr, exp.EQ):
        left, right = expr.left, expr.right
        if isinstance(left, exp.Literal) and isinstance(right, exp.Literal):
            return left.name == right.name
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            return left.name.lower() == right.name.lower() and (left.table or "").lower() == (right.table or "").lower()
    if isinstance(expr, exp.Or):
        return _is_tautology(expr.left) or _is_tautology(expr.right)
    if isinstance(expr, exp.And):
        return _is_tautology(expr.left) and _is_tautology(expr.right)
    return False


def _determine_operation_and_tier(root: exp.Expression) -> tuple[SqlOperation, RiskTierLiteral]:
    """Classify the root AST node into one of the 4 permitted operations and its RiskTier."""
    if isinstance(root, exp.Select):
        return "SELECT", "read"
    if isinstance(root, exp.Insert):
        return "INSERT", "write_local"
    if isinstance(root, exp.Update):
        return "UPDATE", "write_local"
    if isinstance(root, exp.Delete):
        return "DELETE", "irreversible"
    raise SqlSecurityError(
        f"Forbidden SQL statement type '{type(root).__name__}'. "
        "Only SELECT, INSERT, UPDATE, and DELETE statements are permitted."
    )


def _check_ast_nodes_and_functions(root: exp.Expression, operation: SqlOperation) -> None:
    """Walk every node in the AST to block DDL, DCL, TCL, admin commands, writable CTEs, and dangerous functions."""
    if operation == "SELECT" and root.args.get("into") is not None:
        raise SqlSecurityError("SELECT ... INTO table creation is strictly forbidden.")

    for node in root.walk():
        if node is not root and isinstance(node, FORBIDDEN_AST_NODE_TYPES):
            raise SqlSecurityError(
                f"Forbidden SQL construct '{type(node).__name__}' detected in statement."
            )
        if isinstance(node, FORBIDDEN_AST_NODE_TYPES):
            raise SqlSecurityError(
                f"Forbidden SQL statement '{type(node).__name__}'. DDL and administrative statements are blocked."
            )

        # Block writable CTEs or nested mutations inside SELECT queries
        if operation == "SELECT" and isinstance(node, (exp.Insert, exp.Update, exp.Delete)):
            raise SqlSecurityError(
                f"Forbidden mutation node '{type(node).__name__}' inside a SELECT query."
            )

        # Block dangerous functions
        if isinstance(node, exp.Anonymous):
            fn_name = (node.name or "").strip().lower()
            if fn_name in FORBIDDEN_SQL_FUNCTIONS:
                raise SqlSecurityError(f"Forbidden SQL function '{fn_name}()' is blocked by sandbox.")
        elif isinstance(node, exp.Func):
            fn_sql_name = (node.sql_name() or "").strip().lower()
            fn_this_name = str(getattr(node, "name", "") or "").strip().lower()
            for candidate in (fn_sql_name, fn_this_name):
                if candidate in FORBIDDEN_SQL_FUNCTIONS:
                    raise SqlSecurityError(
                        f"Forbidden SQL function '{candidate}()' is blocked by sandbox."
                    )


def _validate_tables_and_columns(
    root: exp.Expression,
    operation: SqlOperation,
    catalog: SchemaCatalog,
    scope_ctx: Optional[Any],
) -> tuple[List[str], Dict[str, TableSchemaDoc]]:
    """Verify all referenced tables and columns against denylist, SchemaCatalog, and ScopeContext."""
    cte_names: Set[str] = {
        cte.alias_or_name.lower()
        for cte in root.find_all(exp.CTE)
        if cte.alias_or_name
    }

    table_nodes = [
        t for t in root.find_all(exp.Table) if (t.name or "").lower() not in cte_names
    ]
    if not table_nodes:
        raise SqlValidationError("SQL statement must reference at least one valid database table.")

    mode: Literal["read", "write"] = "read" if operation == "SELECT" else "write"
    target_tables: List[str] = []
    alias_to_doc: Dict[str, TableSchemaDoc] = {}

    for t_node in table_nodes:
        raw_name = (t_node.name or "").strip()
        norm_name = raw_name.lower()
        db_qualifier = (t_node.db or "").strip().lower()
        catalog_qualifier = (t_node.catalog or "").strip().lower()

        for ident in (norm_name, db_qualifier, catalog_qualifier):
            if ident and ident in FORBIDDEN_SYSTEM_IDENTIFIERS:
                raise SqlSecurityError(
                    f"Access to internal database catalog or system object '{ident}' is strictly forbidden."
                )

        if catalog.is_system_denylisted(norm_name):
            raise SqlSecurityError(
                f"Access to protected system/vault table '{norm_name}' is strictly forbidden."
            )

        if norm_name not in catalog.metadata.tables:
            accessible_names = sorted(catalog.get_accessible_tables(scope_ctx=scope_ctx, mode="read").keys())
            raise SqlValidationError(
                f"Unknown table '{raw_name}'. Accessible tables in current scope: {accessible_names}"
            )

        if mode == "write" and norm_name in READ_ONLY_TABLES:
            raise SqlSecurityError(
                f"Table '{raw_name}' is read-only and cannot be modified via {operation}."
            )

        if not catalog.is_table_accessible(norm_name, scope_ctx=scope_ctx, mode=mode):
            active_scope = getattr(scope_ctx, "scope", "unknown") if scope_ctx else "unscoped"
            raise SqlSecurityError(
                f"Active scope '{active_scope}' is not authorized for '{mode}' access to table '{raw_name}'."
            )

        t_doc = catalog.get_table_doc(norm_name, scope_ctx=scope_ctx, mode=mode)
        assert t_doc is not None
        if norm_name not in target_tables:
            target_tables.append(norm_name)

        alias_to_doc[norm_name] = t_doc
        alias_name = (t_node.alias or "").strip().lower()
        if alias_name:
            alias_to_doc[alias_name] = t_doc

    # For DML operations (INSERT, UPDATE, DELETE), only 1 target table is permitted
    if operation in {"INSERT", "UPDATE", "DELETE"} and len(target_tables) > 1:
        raise SqlSecurityError(
            f"{operation} statements may only target a single table; found {target_tables}."
        )

    # Validate explicit INSERT schema columns
    if isinstance(root, exp.Insert) and isinstance(root.this, exp.Schema):
        primary_doc = alias_to_doc[target_tables[0]]
        valid_cols = {c.lower() for c in primary_doc.columns}
        for col_expr in root.this.expressions:
            col_name = col_expr.name.lower()
            if col_name not in valid_cols:
                col_hints = [
                    f"{c.name} ({c.data_type}: {c.comment})"
                    for c in primary_doc.columns.values()
                ]
                raise SqlValidationError(
                    f"Unknown column '{col_expr.name}' on table '{primary_doc.name}'. "
                    f"Valid columns: {', '.join(col_hints)}"
                )

    # Collect SELECT expression aliases so ORDER BY / GROUP BY / HAVING can reference them
    select_aliases: Set[str] = {
        alias_node.alias.lower()
        for alias_node in root.find_all(exp.Alias)
        if alias_node.alias
    }

    # Validate all exp.Column references
    all_valid_cols: Set[str] = {
        col_name.lower()
        for doc in alias_to_doc.values()
        for col_name in doc.columns
    }
    for col_node in root.find_all(exp.Column):
        if isinstance(col_node.this, exp.Star):
            continue
        col_name = (col_node.name or "").strip()
        if not col_name or col_name == "*":
            continue
        col_lower = col_name.lower()
        tbl_qual = (col_node.table or "").strip().lower()

        if tbl_qual:
            if tbl_qual in cte_names:
                continue
            if tbl_qual not in alias_to_doc:
                raise SqlValidationError(
                    f"Unknown table qualifier '{col_node.table}' on column '{col_node.table}.{col_name}'."
                )
            target_doc = alias_to_doc[tbl_qual]
            if col_lower not in {c.lower() for c in target_doc.columns}:
                col_hints = [
                    f"{c.name} ({c.data_type}: {c.comment})"
                    for c in target_doc.columns.values()
                ]
                raise SqlValidationError(
                    f"Unknown column '{col_name}' on table '{target_doc.name}'. "
                    f"Valid columns on '{target_doc.name}': {', '.join(col_hints)}"
                )
        else:
            if col_lower not in all_valid_cols and col_lower not in select_aliases and not cte_names:
                primary_doc = alias_to_doc[target_tables[0]]
                col_hints = [
                    f"{c.name} ({c.data_type}: {c.comment})"
                    for c in primary_doc.columns.values()
                ]
                raise SqlValidationError(
                    f"Unknown column '{col_name}' in query targeting {target_tables}. "
                    f"Valid columns on '{primary_doc.name}': {', '.join(col_hints)}"
                )

    return target_tables, alias_to_doc


def _build_guard_predicate(
    t_doc: TableSchemaDoc,
    qualifier: Optional[str],
    enforce_profile: bool,
    enforce_scope: bool,
) -> Optional[exp.Expression]:
    """Construct AST predicate enforcing profile_id and scope isolation for a table."""
    prefix = f"{qualifier}." if qualifier else ""
    clauses: List[str] = []

    if enforce_profile:
        if t_doc.has_profile_id:
            clauses.append(f"{prefix}profile_id = :__ctx_profile_id")
        elif t_doc.name == "profiles":
            clauses.append(f"{prefix}id = :__ctx_profile_id")

    if enforce_scope and t_doc.has_scope:
        clauses.append(f"{prefix}scope = :__ctx_scope")

    if not clauses:
        return None
    return sqlglot.parse_one(" AND ".join(clauses), read="sqlite")


def _attach_where_guard(
    node: exp.Select | exp.Update | exp.Delete,
    guard_expr: exp.Expression,
) -> None:
    """Wrap any existing WHERE clause in parentheses and AND it with guard_expr."""
    existing_where = node.args.get("where")
    if existing_where is not None and existing_where.this is not None:
        wrapped_user_where = exp.Paren(this=existing_where.this)
        combined = exp.And(this=wrapped_user_where, expression=exp.Paren(this=guard_expr))
        existing_where.set("this", combined)
    else:
        node.where(guard_expr, copy=False)


def _rewrite_select_ast(
    root: exp.Select,
    alias_to_doc: Dict[str, TableSchemaDoc],
    cte_names: Set[str],
    enforce_profile: bool,
    enforce_scope: bool,
    max_limit: int,
) -> None:
    """Inject profile_id and scope predicates into every SELECT block and enforce LIMIT."""
    select_nodes = [root, *[s for s in root.find_all(exp.Select) if s is not root]]
    for sel in select_nodes:
        local_tables: List[exp.Table] = []
        from_clause = sel.args.get("from_")
        if isinstance(from_clause, exp.From) and isinstance(from_clause.this, exp.Table):
            local_tables.append(from_clause.this)
        for join_node in sel.args.get("joins") or []:
            if isinstance(join_node, exp.Join) and isinstance(join_node.this, exp.Table):
                local_tables.append(join_node.this)

        guards: List[exp.Expression] = []
        for tbl in local_tables:
            t_name = (tbl.name or "").lower()
            if t_name in cte_names:
                continue
            t_doc = alias_to_doc.get(t_name)
            if t_doc is None:
                continue
            qualifier = tbl.alias_or_name
            g = _build_guard_predicate(
                t_doc,
                qualifier=qualifier,
                enforce_profile=enforce_profile,
                enforce_scope=enforce_scope,
            )
            if g is not None:
                guards.append(g)

        if guards:
            combined_guard = guards[0]
            for extra in guards[1:]:
                combined_guard = exp.And(this=combined_guard, expression=extra)
            _attach_where_guard(sel, combined_guard)

    # Enforce bounded LIMIT on outer SELECT
    limit_node = root.args.get("limit")
    if limit_node is None:
        root.limit(max_limit, copy=False)
    elif isinstance(limit_node, exp.Limit) and isinstance(limit_node.expression, exp.Literal):
        try:
            current_limit = int(limit_node.expression.name)
            if current_limit > MAX_SELECT_LIMIT or current_limit <= 0:
                root.limit( min(max_limit, MAX_SELECT_LIMIT), copy=False)
        except (TypeError, ValueError):
            root.limit(max_limit, copy=False)


def _rewrite_insert_ast(
    root: exp.Insert,
    t_doc: TableSchemaDoc,
    bound_params: Dict[str, Any],
    enforce_profile: bool,
    enforce_scope: bool,
) -> None:
    """Validate and rewrite INSERT ... VALUES to inject id, profile_id, scope, and timestamps."""
    if not isinstance(root.expression, exp.Values):
        raise SqlSecurityError(
            "Only parameterized INSERT INTO ... VALUES (...) statements are permitted; "
            "INSERT INTO ... SELECT is blocked."
        )
    if not isinstance(root.this, exp.Schema) or not root.this.expressions:
        raise SqlValidationError(
            f"INSERT INTO {t_doc.name} must explicitly list target column names."
        )

    tuples = list(root.expression.expressions)
    if len(tuples) != 1 or not isinstance(tuples[0], exp.Tuple):
        raise SqlSecurityError("Dynamic INSERT statements must insert exactly one row per call.")

    col_identifiers = list(root.this.expressions)
    val_expressions = list(tuples[0].expressions)
    if len(col_identifiers) != len(val_expressions):
        raise SqlValidationError(
            f"INSERT column count ({len(col_identifiers)}) does not match VALUES count ({len(val_expressions)})."
        )

    col_index_map: Dict[str, int] = {
        col_id.name.lower(): idx for idx, col_id in enumerate(col_identifiers)
    }

    def _set_or_append_col(col_name: str, param_name: str) -> None:
        placeholder = exp.Placeholder(this=param_name)
        if col_name.lower() in col_index_map:
            idx = col_index_map[col_name.lower()]
            val_expressions[idx] = placeholder
        else:
            col_index_map[col_name.lower()] = len(col_identifiers)
            col_identifiers.append(exp.Identifier(this=col_name, quoted=False))
            val_expressions.append(placeholder)

    if enforce_profile and t_doc.has_profile_id:
        _set_or_append_col("profile_id", "__ctx_profile_id")

    if enforce_scope and t_doc.has_scope:
        _set_or_append_col("scope", "__ctx_scope")

    if "id" in t_doc.columns and "id" not in col_index_map:
        bound_params.setdefault("__ctx_id", str(uuid.uuid4()))
        _set_or_append_col("id", "__ctx_id")

    if "created_at" in t_doc.columns and "created_at" not in col_index_map:
        _set_or_append_col("created_at", "__ctx_now")

    if "updated_at" in t_doc.columns and "updated_at" not in col_index_map:
        _set_or_append_col("updated_at", "__ctx_now")

    for col_doc in t_doc.columns.values():
        if (
            not col_doc.nullable
            and not col_doc.primary_key
            and col_doc.name.lower() not in col_index_map
            and col_doc.scalar_default is not None
        ):
            def_param = f"__ctx_def_{col_doc.name}"
            bound_params.setdefault(def_param, col_doc.scalar_default)
            _set_or_append_col(col_doc.name, def_param)

    root.this.set("expressions", col_identifiers)
    tuples[0].set("expressions", val_expressions)


def _rewrite_update_ast(
    root: exp.Update,
    t_doc: TableSchemaDoc,
    enforce_profile: bool,
    enforce_scope: bool,
) -> None:
    """Validate and rewrite UPDATE to block immutable columns, require WHERE, and inject tenant/scope guards."""
    assignments = list(root.expressions)
    if not assignments:
        raise SqlValidationError("UPDATE statement must specify at least one column assignment in SET.")

    assigned_cols: Set[str] = set()
    for assign in assignments:
        if isinstance(assign, exp.EQ) and isinstance(assign.left, exp.Column):
            c_name = assign.left.name.lower()
            if c_name in IMMUTABLE_COLUMNS:
                raise SqlSecurityError(
                    f"Cannot modify immutable ownership/audit column '{assign.left.name}' in UPDATE."
                )
            assigned_cols.add(c_name)

    where_node = root.args.get("where")
    if where_node is None or _is_tautology(where_node.this):
        raise SqlSecurityError(
            "Unfiltered or tautological UPDATE statements are blocked. "
            "Provide an explicit WHERE clause (e.g. WHERE id = :id or WHERE slug = :slug)."
        )

    if "updated_at" in t_doc.columns and "updated_at" not in assigned_cols:
        assignments.append(sqlglot.parse_one("updated_at = :__ctx_now", read="sqlite"))
        root.set("expressions", assignments)

    tbl_node = root.this
    qualifier = tbl_node.alias if isinstance(tbl_node, exp.Table) and tbl_node.alias else None
    guard = _build_guard_predicate(
        t_doc,
        qualifier=qualifier,
        enforce_profile=enforce_profile,
        enforce_scope=enforce_scope,
    )
    if guard is not None:
        _attach_where_guard(root, guard)


def _rewrite_delete_ast(
    root: exp.Delete,
    t_doc: TableSchemaDoc,
    enforce_profile: bool,
    enforce_scope: bool,
) -> None:
    """Validate and rewrite DELETE to require an explicit non-tautological WHERE and inject tenant/scope guards."""
    where_node = root.args.get("where")
    if where_node is None or _is_tautology(where_node.this):
        raise SqlSecurityError(
            "Unfiltered or tautological DELETE statements are blocked. "
            "Provide an explicit WHERE clause identifying the target record(s) (e.g. WHERE id = :id)."
        )

    tbl_node = root.this
    qualifier = tbl_node.alias if isinstance(tbl_node, exp.Table) and tbl_node.alias else None
    guard = _build_guard_predicate(
        t_doc,
        qualifier=qualifier,
        enforce_profile=enforce_profile,
        enforce_scope=enforce_scope,
    )
    if guard is not None:
        _attach_where_guard(root, guard)


def validate_and_rewrite_sql(
    statement: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    profile_id: Optional[str] = None,
    scope_ctx: Optional[Any] = None,
    schema_catalog: Optional[SchemaCatalog] = None,
    source_dialect: str = "sqlite",
    target_dialect: str = "sqlite",
    allowed_operations: Optional[Iterable[SqlOperation]] = None,
    max_limit: int = DEFAULT_SELECT_LIMIT,
) -> ValidatedSqlPlan:
    """Parse, validate, rewrite, and transpile a SQL statement through the 5-stage AST firewall.

    Args:
        statement: Raw parameterized SQL string (`SELECT`, `INSERT`, `UPDATE`, or `DELETE`).
        params: Parameter bindings dictionary.
        profile_id: Active tenant profile ID (overrides or supplements ``scope_ctx.profile_id``).
        scope_ctx: Optional ``ScopeContext`` governing domain scope isolation.
        schema_catalog: Optional ``SchemaCatalog`` (defaults to ``get_schema_catalog()``).
        source_dialect: Input SQL dialect hint.
        target_dialect: Target execution engine dialect (`sqlite`, `postgres`, `mysql`, `tsql`, `duckdb`).
        allowed_operations: Subset of allowed operations (defaults to all 4 DQL/DML operations).
        max_limit: Maximum rows returned by a `SELECT` query (defaults to 100).

    Returns:
        ``ValidatedSqlPlan`` containing the rewritten, dialect-transpiled SQL and bound parameters.
    """
    if not statement or not statement.strip():
        raise SqlValidationError("SQL statement cannot be empty.")

    raw_sql = statement.strip()

    # Defense-in-depth: check leading token before AST parsing
    first_token_match = re.match(r"^\s*([a-zA-Z_]+)", raw_sql)
    if first_token_match:
        first_word = first_token_match.group(1).upper()
        if first_word in FORBIDDEN_LEADING_KEYWORDS:
            raise SqlSecurityError(
                f"Forbidden SQL command '{first_word}'. Only SELECT, INSERT, UPDATE, and DELETE are allowed."
            )

    # Check for stacked statements separated by semicolons
    stripped_trailing = raw_sql.rstrip("; \t\r\n")
    if not stripped_trailing:
        raise SqlValidationError("SQL statement cannot be empty.")

    read_dialect = normalize_sqlglot_dialect(source_dialect)
    write_dialect = normalize_sqlglot_dialect(target_dialect)

    try:
        parsed_statements = [
            stmt
            for stmt in sqlglot.parse(stripped_trailing, read=read_dialect)
            if stmt is not None
        ]
    except (ParseError, TokenError) as exc:
        raise SqlValidationError(f"SQL syntax error: {exc}") from exc

    if len(parsed_statements) != 1:
        raise SqlSecurityError(
            f"Multi-statement stacked SQL queries are strictly forbidden (parsed {len(parsed_statements)} statements)."
        )

    root = parsed_statements[0]
    operation, risk_tier = _determine_operation_and_tier(root)

    if allowed_operations is not None:
        allowed_set: Set[str] = {op.upper() for op in allowed_operations}
        if operation not in allowed_set:
            raise SqlSecurityError(
                f"Operation '{operation}' is not permitted in this tool; allowed operations: {sorted(allowed_set)}."
            )

    # Stage 2: Recursive AST node & function inspection
    _check_ast_nodes_and_functions(root, operation)

    # Stage 3: Table & Column Verification
    catalog = schema_catalog or get_schema_catalog()
    target_tables, alias_to_doc = _validate_tables_and_columns(
        root, operation, catalog, scope_ctx
    )

    # Resolve context bindings
    effective_profile_id = profile_id or (
        getattr(scope_ctx, "profile_id", None) if scope_ctx is not None else None
    )
    effective_scope = (
        getattr(scope_ctx, "scope", None) if scope_ctx is not None else None
    )

    enforce_profile = bool(effective_profile_id)
    enforce_scope = bool(effective_scope)

    bound_params: Dict[str, Any] = dict(params or {})
    now_iso = datetime.now(timezone.utc).isoformat()
    bound_params["__ctx_now"] = now_iso
    if enforce_profile:
        bound_params["__ctx_profile_id"] = str(effective_profile_id)
    if enforce_scope:
        bound_params["__ctx_scope"] = str(effective_scope)

    cte_names: Set[str] = {
        cte.alias_or_name.lower()
        for cte in root.find_all(exp.CTE)
        if cte.alias_or_name
    }

    # Stage 4: Mandatory AST Rewriting
    if isinstance(root, exp.Select):
        _rewrite_select_ast(
            root,
            alias_to_doc=alias_to_doc,
            cte_names=cte_names,
            enforce_profile=enforce_profile,
            enforce_scope=enforce_scope,
            max_limit=max_limit,
        )
    elif isinstance(root, exp.Insert):
        _rewrite_insert_ast(
            root,
            t_doc=alias_to_doc[target_tables[0]],
            bound_params=bound_params,
            enforce_profile=enforce_profile,
            enforce_scope=enforce_scope,
        )
    elif isinstance(root, exp.Update):
        _rewrite_update_ast(
            root,
            t_doc=alias_to_doc[target_tables[0]],
            enforce_profile=enforce_profile,
            enforce_scope=enforce_scope,
        )
    elif isinstance(root, exp.Delete):
        _rewrite_delete_ast(
            root,
            t_doc=alias_to_doc[target_tables[0]],
            enforce_profile=enforce_profile,
            enforce_scope=enforce_scope,
        )

    # Verify all placeholders in the rewritten AST are present in bound_params
    required_placeholders: Set[str] = {
        ph.name for ph in root.find_all(exp.Placeholder) if ph.name
    }
    missing_params = sorted(p for p in required_placeholders if p not in bound_params)
    if missing_params:
        raise SqlValidationError(
            f"Missing bound parameter value(s) for placeholder(s): {missing_params}"
        )

    # Prune unused __ctx_* parameters so SQLAlchemy drivers do not complain about extra binds
    final_params: Dict[str, Any] = {
        k: v
        for k, v in bound_params.items()
        if not k.startswith("__ctx_") or k in required_placeholders
    }

    # Stage 5: Transpile to target SQL dialect while preserving :param syntax for SQLAlchemy text()
    rendered_sql = root.sql(dialect=write_dialect)
    normalized_sql = _normalize_sqlalchemy_placeholders(rendered_sql)

    return ValidatedSqlPlan(
        operation=operation,
        risk_tier=risk_tier,
        target_tables=target_tables,
        rewritten_sql=normalized_sql,
        bound_params=final_params,
        dialect=write_dialect,
        original_sql=raw_sql,
    )


__all__ = [
    "DEFAULT_SELECT_LIMIT",
    "FORBIDDEN_LEADING_KEYWORDS",
    "FORBIDDEN_SQL_FUNCTIONS",
    "FORBIDDEN_SYSTEM_IDENTIFIERS",
    "MAX_SELECT_LIMIT",
    "RiskTierLiteral",
    "SqlOperation",
    "SqlSecurityError",
    "SqlValidationError",
    "ValidatedSqlPlan",
    "normalize_sqlglot_dialect",
    "validate_and_rewrite_sql",
]
