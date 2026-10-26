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

"""Yarvelle Core relational database layer with multi-dialect support (SQLite & PostgreSQL)."""

from yarvelle_core.db.base import Base, ensure_metadata_comments, ensure_table_comments
from yarvelle_core.db.schema_catalog import (
    SYSTEM_DENYLIST_TABLES,
    SchemaCatalog,
    get_schema_catalog,
    infer_table_domain_prefix,
    register_table_scope,
)
from yarvelle_core.db.models import (
    Agent,
    Approval,
    Attachment,
    AuditEventRecord,
    ChatThread,
    Connection,
    ConsentGrant,
    Credential,
    EmailDraft,
    Job,
    KnowledgeBase,
    McpToolPin,
    Note,
    PasswordReset,
    Profile,
    ProfileAccess,
    ProfileConsent,
    ProfileKey,
    Reminder,
    Routine,
    ScopeGrant,
    Session,
    Skill,
    SyncRun,
    SystemSetting,
    User,
    ViewerInvite,
)
from yarvelle_core.db.session import (
    close_db,
    create_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    normalize_database_url,
    reset_engine,
    resolve_database_url,
    sanitize_db_url,
)

__all__ = [
    "Base",
    "ensure_metadata_comments",
    "ensure_table_comments",
    "SchemaCatalog",
    "get_schema_catalog",
    "SYSTEM_DENYLIST_TABLES",
    "infer_table_domain_prefix",
    "register_table_scope",
    "User",
    "Session",
    "PasswordReset",
    "SystemSetting",
    "Agent",
    "Skill",
    "KnowledgeBase",
    "Note",
    "Attachment",
    "AuditEventRecord",
    "ChatThread",
    "Profile",
    "ProfileAccess",
    "ProfileConsent",
    "ProfileKey",
    "Approval",
    "Job",
    "Connection",
    "Credential",
    "ConsentGrant",
    "SyncRun",
    "Routine",
    "McpToolPin",
    "EmailDraft",
    "",
    "ScopeGrant",
    "",
    "ViewerInvite",
    "",
    "",
    "Reminder",
    "",
    "",
    "",
    "create_db_engine",
    "get_engine",
    "get_session_factory",
    "get_db",
    "init_db",
    "close_db",
    "reset_engine",
    "normalize_database_url",
    "sanitize_db_url",
    "resolve_database_url",
]
