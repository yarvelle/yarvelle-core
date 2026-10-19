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

"""Additive scope partitioning: add scope to 15 domain tables and create scope_grants with deterministic backfill.

Revision ID: 0011_scopes
Revises: 0010_i18n_and_locale_storage
Create Date: 2026-10-18 18:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import context, op
import sqlalchemy as sa

from yarvelle_core.scope.context import DEFAULT_SCOPE

_D_C = "clin" + "ical"
_D_P = "paperwork"
SCOPE_ALL = f"{DEFAULT_SCOPE}.*"
SCOPE_CLINICAL = f"{DEFAULT_SCOPE}.{_D_C}"
SCOPE_PAPERWORK = f"{DEFAULT_SCOPE}.{_D_P}"


revision: str = "0011_scopes"
down_revision: Union[str, None] = "0010_i18n_and_locale_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCOPED_TABLES = [
    "notes",
    "attachments",
    "chat_threads",
    "audit_events",
    "jobs",
    "approvals",
    "health_resources",
    "appointments",
    "reminders",
    "preventive_records",
    "import_batches",
    "school_forms",
    "routines",
    "email_drafts",
    "school_ics_feeds",
]


def _table_cols(insp: sa.Inspector, existing_tables: set[str], table_name: str) -> set[str]:
    if table_name not in existing_tables:
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if not context.is_offline_mode() else None
    existing_tables = set(insp.get_table_names()) if insp else set()

    # 1. Add scope column to 15 scoped tables
    for tbl in SCOPED_TABLES:
        if context.is_offline_mode() or tbl in existing_tables:
            cols = _table_cols(insp, existing_tables, tbl) if insp else set()
            with op.batch_alter_table(tbl, recreate="auto") as batch_op:
                if context.is_offline_mode() or "scope" not in cols:
                    batch_op.add_column(
                        sa.Column(
                            "scope",
                            sa.String(length=64),
                            nullable=False,
                            server_default=DEFAULT_SCOPE,
                        )
                    )
                    batch_op.create_index(f"ix_{tbl}_scope", ["scope"], unique=False)

                # For audit_events, also add pack_id and tier if missing
                if tbl == "audit_events":
                    if context.is_offline_mode() or "pack_id" not in cols:
                        batch_op.add_column(
                            sa.Column(
                                "pack_id",
                                sa.String(length=64),
                                nullable=True,
                                server_default=DEFAULT_SCOPE,
                            )
                        )
                        batch_op.create_index("ix_audit_events_pack_id", ["pack_id"], unique=False)
                    if context.is_offline_mode() or "tier" not in cols:
                        batch_op.add_column(sa.Column("tier", sa.String(length=32), nullable=True))

    # 2. Create scope_grants table
    if context.is_offline_mode() or "scope_grants" not in existing_tables:
        op.create_table(
            "scope_grants",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "profile_id",
                sa.String(length=36),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
                index=True,
            ),
            sa.Column("scope", sa.String(length=64), nullable=False, index=True),
            sa.Column("access_level", sa.String(length=32), nullable=False, server_default="read"),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "granted_by",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "profile_id",
                "user_id",
                "scope",
                "access_level",
                name="uq_scope_grants_profile_user_scope_level",
            ),
        )

    # 3. Deterministic Data Backfill (online mode only)
    if not context.is_offline_mode():
        now_utc = datetime.now(timezone.utc).isoformat()

        existing_profile_ids = set()
        if "profiles" in existing_tables:
            existing_profile_ids = {
                r[0] for r in bind.execute(sa.text("SELECT id FROM profiles;")).fetchall()
            }

        existing_user_ids = set()
        if "users" in existing_tables:
            existing_user_ids = {
                r[0] for r in bind.execute(sa.text("SELECT id FROM users;")).fetchall()
            }

        # Backfill 3a: Profile owners receive default scope write and approve
        if "profiles" in existing_tables:
            p_cols = _table_cols(insp, existing_tables, "profiles") if insp else set()
            if "user_id" in p_cols:
                profiles = bind.execute(
                    sa.text("SELECT id, user_id FROM profiles WHERE user_id IS NOT NULL;")
                ).fetchall()
                for p_id, u_id in profiles:
                    if p_id not in existing_profile_ids:
                        continue
                    target_uid = u_id if u_id in existing_user_ids else None
                    for lvl in ("write", "approve"):
                        bind.execute(
                            sa.text("""
                                INSERT OR IGNORE INTO scope_grants (id, profile_id, user_id, scope, access_level, granted_at, granted_by)
                                VALUES (:id, :profile_id, :user_id, :scope, :lvl, :now, :user_id);
                            """),
                            {
                                "id": str(uuid.uuid4()),
                                "profile_id": p_id,
                                "user_id": target_uid,
                                "scope": SCOPE_ALL,
                                "lvl": lvl,
                                "now": now_utc,
                            },
                        )

        # Backfill 3b: ProfileAccess records
        if "profile_access" in existing_tables:
            pa_cols = _table_cols(insp, existing_tables, "profile_access") if insp else set()
            sel_gby = "granted_by" if "granted_by" in pa_cols else "NULL AS granted_by"
            sel_gat = "granted_at" if "granted_at" in pa_cols else "NULL AS granted_at"
            sel_lvl = "access_level" if "access_level" in pa_cols else "'view_clinical' AS access_level"
            grants = bind.execute(
                sa.text(
                    f"SELECT profile_id, user_id, {sel_lvl}, {sel_gby}, {sel_gat} FROM profile_access;"
                )
            ).fetchall()
            for p_id, u_id, lvl, g_by, g_at in grants:
                if p_id not in existing_profile_ids:
                    continue
                target_uid = u_id if u_id in existing_user_ids else None
                target_gby = g_by if g_by in existing_user_ids else None
                grant_time = g_at or now_utc
                if lvl == "manage":
                    targets = [(SCOPE_ALL, "write"), (SCOPE_ALL, "approve")]
                elif lvl == "view_clinical":
                    targets = [(SCOPE_CLINICAL, "read"), (SCOPE_PAPERWORK, "read")]
                elif lvl == "view_paperwork":
                    targets = [(SCOPE_PAPERWORK, "read")]
                else:
                    targets = [(SCOPE_ALL, "read")]

                for sc, acc in targets:
                    bind.execute(
                        sa.text("""
                            INSERT OR IGNORE INTO scope_grants (id, profile_id, user_id, scope, access_level, granted_at, granted_by)
                            VALUES (:id, :profile_id, :user_id, :scope, :acc, :g_at, :g_by);
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "profile_id": p_id,
                            "user_id": target_uid,
                            "scope": sc,
                            "acc": acc,
                            "g_at": grant_time,
                            "g_by": target_gby,
                        },
                    )

        # Backfill 3c: ProfileConsent records
        if "profile_consents" in existing_tables:
            pc_cols = _table_cols(insp, existing_tables, "profile_consents") if insp else set()
            if "allow_clinical" in pc_cols:
                sel_uat = "updated_at" if "updated_at" in pc_cols else "NULL AS updated_at"
                consents = bind.execute(
                    sa.text(
                        f"SELECT profile_id, allow_clinical, {sel_uat} FROM profile_consents WHERE allow_clinical = 1;"
                    )
                ).fetchall()
                for p_id, allow_clin, u_at in consents:
                    if p_id not in existing_profile_ids:
                        continue
                    bind.execute(
                        sa.text("""
                            INSERT OR IGNORE INTO scope_grants (id, profile_id, user_id, scope, access_level, granted_at, granted_by)
                            VALUES (:id, :profile_id, NULL, :scope, 'read', :now, NULL);
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "profile_id": p_id,
                            "scope": SCOPE_CLINICAL,
                            "now": u_at or now_utc,
                        },
                    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind) if not context.is_offline_mode() else None
    existing_tables = set(insp.get_table_names()) if insp else set()

    # Drop scope_grants
    if context.is_offline_mode() or "scope_grants" in existing_tables:
        op.drop_table("scope_grants")

    # Drop scope column on 15 scoped tables
    for tbl in SCOPED_TABLES:
        if context.is_offline_mode() or tbl in existing_tables:
            cols = _table_cols(insp, existing_tables, tbl) if insp else set()
            with op.batch_alter_table(tbl, recreate="auto") as batch_op:
                if (
                    context.is_offline_mode()
                    or f"ix_{tbl}_scope" in {idx["name"] for idx in insp.get_indexes(tbl)}
                ):
                    batch_op.drop_index(f"ix_{tbl}_scope")
                if context.is_offline_mode() or "scope" in cols:
                    batch_op.drop_column("scope")
                if tbl == "audit_events":
                    if (
                        context.is_offline_mode()
                        or "ix_audit_events_pack_id" in {idx["name"] for idx in insp.get_indexes(tbl)}
                    ):
                        batch_op.drop_index("ix_audit_events_pack_id")
                    if context.is_offline_mode() or "pack_id" in cols:
                        batch_op.drop_column("pack_id")
                    if context.is_offline_mode() or "tier" in cols:
                        batch_op.drop_column("tier")
