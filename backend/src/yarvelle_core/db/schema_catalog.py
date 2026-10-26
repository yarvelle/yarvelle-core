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

"""Database Schema Catalog & M-Schema Documentation Generator.

Introspects SQLAlchemy declarative metadata (and optional live database engines)
to produce structured table, column, foreign-key, and index documentation for
dynamic SQL query planning and AST validation. Enforces system/vault table
denylisting and domain-scope visibility filtering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, FrozenSet, Iterable, List, Literal, Optional, Set

from sqlalchemy import MetaData, Table
from yarvelle_core.db.base import Base, ensure_metadata_comments
import yarvelle_core.db.models  # noqa: F401 — ensure core models are registered on Base.metadata

# System, authentication, cryptographic vault, and audit tables that must NEVER
# be accessed or mutated by LLM-planned dynamic SQL queries.
SYSTEM_DENYLIST_TABLES: FrozenSet[str] = frozenset(
    {
        "users",
        "sessions",
        "password_resets",
        "system_settings",
        "credentials",
        "profile_keys",
        "audit_events",
        "approvals",
        "mcp_tool_pins",
        "scope_grants",
        "profile_access",
        "profile_consents",
        "consent_grants",
        "viewer_invites",
        "alembic_version",
    }
)

# Tables that may be read via SELECT in dynamic queries but must not be mutated
# directly via dynamic INSERT/UPDATE/DELETE.
READ_ONLY_TABLES: FrozenSet[str] = frozenset(
    {
        "profiles",
        "agent",
        "skill",
        "knowledge_base",
        "connections",
        "sync_runs",
    }
)

# Core tables that exist across all domain scopes (isolated via profile_id + scope column).
CORE_SHARED_TABLES: FrozenSet[str] = frozenset(
    {
        "profiles",
        "profile_ui_preferences",
        "agent",
        "skill",
        "knowledge_base",
        "notes",
        "attachments",
        "chat_threads",
        "connections",
        "jobs",
        "reminders",
        "sync_runs",
        "routines",
        "email_drafts",
        "cross_domain_links",
        "households",
        "household_members",
    }
)

# Columns automatically populated or enforced by the runtime / AST sandbox on INSERT/UPDATE.
AUTO_INJECTED_COLUMNS: FrozenSet[str] = frozenset(
    {
        "id",
        "profile_id",
        "user_id",
        "scope",
        "created_at",
        "updated_at",
    }
)

# Columns that must never be modified by a dynamic UPDATE statement.
IMMUTABLE_COLUMNS: FrozenSet[str] = frozenset(
    {
        "id",
        "profile_id",
        "user_id",
        "scope",
        "created_at",
    }
)

_CUSTOM_TABLE_SCOPES: Dict[str, str] = {}


def register_table_scope(table_name: str, domain_prefix: str) -> None:
    """Register an explicit domain scope prefix for a pack table."""
    _CUSTOM_TABLE_SCOPES[table_name.strip().lower()] = domain_prefix.strip().lower()


def infer_table_domain_prefix(table_name: str) -> Optional[str]:
    """Infer the owning domain prefix for a table, or None if it is a core shared table."""
    norm = table_name.strip().lower()
    if norm in _CUSTOM_TABLE_SCOPES:
        return _CUSTOM_TABLE_SCOPES[norm]
    if norm in CORE_SHARED_TABLES or norm in SYSTEM_DENYLIST_TABLES:
        return None
    if "_" in norm:
        prefix = norm.split("_", 1)[0]
        if prefix:
            return prefix
    return None


def _extract_examples_from_comment(comment: str) -> List[str]:
    """Extract enumerated example values from a column comment if present."""
    if not comment:
        return []
    # Match patterns like "status: pending, completed, snoozed" or "(e.g. 'a', 'b')"
    m_colon = re.search(
        r"(?:status|category|type|role|frequency|level|state|format|classification|source)\s*:\s*([a-z0-9_,\s'-]+)$",
        comment,
        re.IGNORECASE,
    )
    if m_colon:
        raw_items = [item.strip(" '\"\t.") for item in m_colon.group(1).split(",")]
        cleaned = [item for item in raw_items if item and len(item) <= 32 and " " not in item]
        if len(cleaned) >= 2:
            return cleaned[:6]
    return []


@dataclass(frozen=True)
class ColumnSchemaDoc:
    """Structured documentation for a single database column."""

    name: str
    data_type: str
    nullable: bool
    primary_key: bool
    foreign_keys: List[str] = field(default_factory=list)
    default: Optional[str] = None
    scalar_default: Optional[Any] = None
    comment: str = ""
    auto_injected: bool = False
    immutable: bool = False
    examples: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class IndexSchemaDoc:
    """Structured documentation for a database index."""

    name: str
    columns: List[str]
    unique: bool = False
    comment: str = ""


@dataclass(frozen=True)
class TableSchemaDoc:
    """Structured documentation for a database table, its columns, and its indexes."""

    name: str
    comment: str
    has_profile_id: bool
    has_scope: bool
    domain_prefix: Optional[str]
    read_only: bool
    columns: Dict[str, ColumnSchemaDoc]
    indexes: List[IndexSchemaDoc]


class SchemaCatalog:
    """Introspects SQLAlchemy metadata to provide scope-filtered schema documentation and M-Schema."""

    def __init__(self, metadata: Optional[MetaData] = None) -> None:
        self._metadata = metadata or Base.metadata
        ensure_metadata_comments(self._metadata)

    @property
    def metadata(self) -> MetaData:
        return self._metadata

    def refresh(self) -> None:
        """Re-synchronize comments across all tables currently registered in metadata."""
        ensure_metadata_comments(self._metadata)

    def _build_table_doc(self, table: Table) -> TableSchemaDoc:
        ensure_metadata_comments(self._metadata)
        cols: Dict[str, ColumnSchemaDoc] = {}
        for col in table.columns:
            fk_targets = sorted(fk.target_fullname for fk in col.foreign_keys)
            default_val: Optional[str] = None
            scalar_default: Optional[Any] = None
            if col.server_default is not None and hasattr(col.server_default, "arg"):
                arg = getattr(col.server_default, "arg")
                if isinstance(arg, str):
                    default_val = arg.strip("'\"")
                    scalar_default = default_val
            elif col.default is not None and getattr(col.default, "is_scalar", False):
                scalar_arg = getattr(col.default, "arg", None)
                if isinstance(scalar_arg, (str, int, float, bool)):
                    default_val = str(scalar_arg)
                    scalar_default = scalar_arg

            col_comment = (col.comment or col.doc or "").strip()
            examples = _extract_examples_from_comment(col_comment)
            cols[col.name] = ColumnSchemaDoc(
                name=col.name,
                data_type=str(col.type),
                nullable=bool(col.nullable),
                primary_key=bool(col.primary_key),
                foreign_keys=fk_targets,
                default=default_val,
                scalar_default=scalar_default,
                comment=col_comment,
                auto_injected=col.name in AUTO_INJECTED_COLUMNS,
                immutable=col.name in IMMUTABLE_COLUMNS,
                examples=examples,
            )

        idxs: List[IndexSchemaDoc] = []
        for idx in sorted(table.indexes, key=lambda i: i.name or ""):
            idx_comment = (idx.info.get("comment") or getattr(idx, "comment", "") or "").strip()
            idxs.append(
                IndexSchemaDoc(
                    name=idx.name or f"ix_{table.name}",
                    columns=[c.name for c in idx.columns],
                    unique=bool(idx.unique),
                    comment=idx_comment,
                )
            )

        t_name = table.name.lower()
        return TableSchemaDoc(
            name=table.name,
            comment=(table.comment or "").strip(),
            has_profile_id="profile_id" in cols,
            has_scope="scope" in cols,
            domain_prefix=infer_table_domain_prefix(t_name),
            read_only=t_name in READ_ONLY_TABLES,
            columns=cols,
            indexes=idxs,
        )

    def is_system_denylisted(self, table_name: str) -> bool:
        """Return True if the table is in the hard security denylist."""
        return table_name.strip().lower() in SYSTEM_DENYLIST_TABLES

    def is_table_accessible(
        self,
        table_name: str,
        scope_ctx: Optional[Any] = None,
        mode: Literal["read", "write"] = "read",
    ) -> bool:
        """Check whether ``table_name`` is accessible under ``scope_ctx`` for ``mode``."""
        norm = table_name.strip().lower()
        if norm in SYSTEM_DENYLIST_TABLES:
            return False
        if norm not in self._metadata.tables:
            return False
        if mode == "write" and norm in READ_ONLY_TABLES:
            return False

        if scope_ctx is None:
            return True

        domain_prefix = infer_table_domain_prefix(norm)
        if domain_prefix is None:
            # Core shared table (isolated at row-level by profile_id / scope)
            return True

        active_scope = str(getattr(scope_ctx, "scope", "") or "").strip().lower()
        active_domain = active_scope.split(".", 1)[0] if active_scope else ""

        if mode == "write":
            can_write_fn = getattr(scope_ctx, "can_write_scope", None)
            if callable(can_write_fn):
                return bool(can_write_fn(domain_prefix) or active_domain == domain_prefix)
            return active_domain == domain_prefix

        # Read mode: check same domain or cross-scope read authorization
        if active_domain == domain_prefix:
            return True

        can_read_fn = getattr(scope_ctx, "can_read_scope", None)
        if callable(can_read_fn):
            if can_read_fn(domain_prefix) or can_read_fn(f"{domain_prefix}.*"):
                return True

        # Check declared_reads & granted_scopes for prefix match (e.g., 'finance.accounts')
        declared_reads: Iterable[str] = getattr(scope_ctx, "declared_reads", ()) or ()
        granted_scopes: Iterable[str] = getattr(scope_ctx, "granted_scopes", ()) or ()

        def _matches_domain(patterns: Iterable[str]) -> bool:
            for pat in patterns:
                p = str(pat).strip().lower()
                if p == "*" or p == domain_prefix or p.startswith(f"{domain_prefix}."):
                    return True
            return False

        if _matches_domain(declared_reads) and _matches_domain(granted_scopes):
            return True

        return False

    def get_table_doc(
        self,
        table_name: str,
        scope_ctx: Optional[Any] = None,
        mode: Literal["read", "write"] = "read",
    ) -> Optional[TableSchemaDoc]:
        """Return structured TableSchemaDoc if the table exists and is authorized."""
        norm = table_name.strip().lower()
        if not self.is_table_accessible(norm, scope_ctx=scope_ctx, mode=mode):
            return None
        table = self._metadata.tables.get(norm)
        if table is None:
            return None
        return self._build_table_doc(table)

    def get_accessible_tables(
        self,
        scope_ctx: Optional[Any] = None,
        mode: Literal["read", "write"] = "read",
    ) -> Dict[str, TableSchemaDoc]:
        """Return all accessible tables (excluding denylisted and out-of-scope tables)."""
        result: Dict[str, TableSchemaDoc] = {}
        for table_name in sorted(self._metadata.tables.keys()):
            if self.is_table_accessible(table_name, scope_ctx=scope_ctx, mode=mode):
                result[table_name] = self._build_table_doc(self._metadata.tables[table_name])
        return result

    def prune_tables_for_intent(
        self,
        intent_query: str,
        scope_ctx: Optional[Any] = None,
        max_tables: int = 8,
    ) -> List[str]:
        """Rank and select the most relevant accessible tables for a natural-language query."""
        accessible = self.get_accessible_tables(scope_ctx=scope_ctx, mode="read")
        if not intent_query or not intent_query.strip():
            return list(accessible.keys())[:max_tables]

        tokens = {
            tok.lower()
            for tok in re.findall(r"[a-zA-Z0-9_]+", intent_query.lower())
            if len(tok) >= 2
        }
        scored: List[tuple[int, str]] = []
        for t_name, t_doc in accessible.items():
            score = 0
            t_words = set(t_name.lower().split("_"))
            for tok in tokens:
                if tok == t_name or tok.rstrip("s") == t_name.rstrip("s"):
                    score += 20
                elif tok in t_words or any(tok.rstrip("s") == w.rstrip("s") for w in t_words):
                    score += 12
                if tok in t_doc.comment.lower():
                    score += 4
                for c_name, c_doc in t_doc.columns.items():
                    if tok == c_name.lower() or tok in c_name.lower().split("_"):
                        score += 6
                    elif tok in c_doc.comment.lower():
                        score += 2
            # Give a slight baseline boost to commonly queried user data tables
            if t_name in {"notes", "reminders", "email_drafts", "routines", "attachments"}:
                score += 1
            scored.append((score, t_name))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [name for sc, name in scored if sc > 0][:max_tables]
        if not selected:
            selected = [name for _, name in scored[:max_tables]]
        return selected

    def get_m_schema(
        self,
        scope_ctx: Optional[Any] = None,
        table_names: Optional[Iterable[str]] = None,
        dialect: str = "sqlite",
        include_indexes: bool = True,
    ) -> str:
        """Render compact M-Schema documentation with table, column, and index comments."""
        accessible = self.get_accessible_tables(scope_ctx=scope_ctx, mode="read")
        if table_names is not None:
            requested: Set[str] = {t.strip().lower() for t in table_names}
            selected_docs = [
                doc for name, doc in accessible.items() if name.lower() in requested
            ]
        else:
            selected_docs = list(accessible.values())

        active_scope = (
            str(getattr(scope_ctx, "scope", "default") or "default")
            if scope_ctx is not None
            else "unscoped"
        )
        lines: List[str] = [
            f"【DB_ENGINE】 dialect={dialect} | active_scope={active_scope}",
            "# Security Invariants: Tenant (profile_id) and Scope (scope) predicates are automatically injected by SqlAstSandbox.",
        ]

        for t_doc in selected_docs:
            flags: List[str] = []
            if t_doc.has_profile_id:
                flags.append("TenantKey: profile_id [auto-filtered]")
            if t_doc.has_scope:
                flags.append("ScopedMixin: scope [auto-filtered]")
            if t_doc.read_only:
                flags.append("Access: READ-ONLY")
            else:
                flags.append("Access: SELECT/INSERT/UPDATE/DELETE")
            flag_str = f" ({' | '.join(flags)})" if flags else ""

            lines.append(f"【TABLE】 {t_doc.name}{flag_str}")
            if t_doc.comment:
                lines.append(f"# Comment: {t_doc.comment}")
            lines.append("[")
            col_lines: List[str] = []
            for c_doc in t_doc.columns.values():
                parts: List[str] = [f"{c_doc.name}: {c_doc.data_type}"]
                if c_doc.primary_key:
                    parts.append("PK")
                if not c_doc.nullable and not c_doc.primary_key:
                    parts.append("NOT NULL")
                if c_doc.foreign_keys:
                    parts.append(f"FK -> {', '.join(c_doc.foreign_keys)}")
                if c_doc.default is not None:
                    parts.append(f"Default={c_doc.default!r}")
                if c_doc.auto_injected:
                    parts.append("Auto-Injected")
                if c_doc.comment:
                    parts.append(f'"{c_doc.comment}"')
                if c_doc.examples:
                    parts.append(f"Examples: {c_doc.examples}")
                col_lines.append(f"  ({', '.join(parts)})")
            lines.append(",\n".join(col_lines))
            lines.append("]")

            if include_indexes and t_doc.indexes:
                lines.append("# Indexes:")
                for idx_doc in t_doc.indexes:
                    cols_str = ", ".join(idx_doc.columns)
                    uniq_str = "UNIQUE " if idx_doc.unique else ""
                    lines.append(
                        f"- {idx_doc.name} ({uniq_str}{cols_str}): {idx_doc.comment}"
                    )
            lines.append("")

        return "\n".join(lines).strip()


_DEFAULT_SCHEMA_CATALOG: Optional[SchemaCatalog] = None


def get_schema_catalog() -> SchemaCatalog:
    """Return the singleton SchemaCatalog backed by Base.metadata."""
    global _DEFAULT_SCHEMA_CATALOG
    if _DEFAULT_SCHEMA_CATALOG is None:
        _DEFAULT_SCHEMA_CATALOG = SchemaCatalog()
    return _DEFAULT_SCHEMA_CATALOG


__all__ = [
    "AUTO_INJECTED_COLUMNS",
    "CORE_SHARED_TABLES",
    "ColumnSchemaDoc",
    "IMMUTABLE_COLUMNS",
    "IndexSchemaDoc",
    "READ_ONLY_TABLES",
    "SYSTEM_DENYLIST_TABLES",
    "SchemaCatalog",
    "TableSchemaDoc",
    "get_schema_catalog",
    "infer_table_domain_prefix",
    "register_table_scope",
]
