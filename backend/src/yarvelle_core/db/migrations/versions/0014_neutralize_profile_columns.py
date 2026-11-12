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

"""Neutralize legacy profile consent, invite, and access-level column names.

Renames ``profile_consents.allow_clinical`` to ``allow_assist``,
``viewer_invites.view_clinical`` to ``view_records``, and migrates legacy
``profile_access.access_level = 'view_clinical'`` values to ``'view_records'``.
Idempotent so greenfield databases created from current ORM models upgrade cleanly.

Revision ID: 0014_neutralize_profile_columns
Revises: 0013_turn_tasks
Create Date: 2026-11-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "0014_neutralize_profile_columns"
down_revision: Union[str, None] = "0013_turn_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector() -> sa.Inspector | None:
    """Returns an inspector, or None in offline mode."""
    if context.is_offline_mode():
        return None
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {
        "profile_consents",
        "viewer_invites",
        "profile_access",
    }

    if "profile_consents" in tables:
        cols = {c["name"] for c in insp.get_columns("profile_consents")} if insp is not None else {"allow_clinical"}
        if "allow_clinical" in cols and "allow_assist" not in cols:
            with op.batch_alter_table("profile_consents", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "allow_clinical",
                    new_column_name="allow_assist",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )

    if "viewer_invites" in tables:
        cols = {c["name"] for c in insp.get_columns("viewer_invites")} if insp is not None else {"view_clinical"}
        if "view_clinical" in cols and "view_records" not in cols:
            with op.batch_alter_table("viewer_invites", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "view_clinical",
                    new_column_name="view_records",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )

    if "profile_access" in tables:
        op.execute(
            sa.text(
                "UPDATE profile_access SET access_level = 'view_records' "
                "WHERE access_level = 'view_clinical'"
            )
        )


def downgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {
        "profile_consents",
        "viewer_invites",
        "profile_access",
    }

    if "profile_access" in tables:
        op.execute(
            sa.text(
                "UPDATE profile_access SET access_level = 'view_clinical' "
                "WHERE access_level = 'view_records'"
            )
        )

    if "viewer_invites" in tables:
        cols = {c["name"] for c in insp.get_columns("viewer_invites")} if insp is not None else {"view_records"}
        if "view_records" in cols and "view_clinical" not in cols:
            with op.batch_alter_table("viewer_invites", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "view_records",
                    new_column_name="view_clinical",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )

    if "profile_consents" in tables:
        cols = {c["name"] for c in insp.get_columns("profile_consents")} if insp is not None else {"allow_assist"}
        if "allow_assist" in cols and "allow_clinical" not in cols:
            with op.batch_alter_table("profile_consents", recreate="auto") as batch_op:
                batch_op.alter_column(
                    "allow_assist",
                    new_column_name="allow_clinical",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                )
