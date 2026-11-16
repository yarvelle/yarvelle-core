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

"""Add pinned column to notes table (Issue #65).

Adds ``notes.pinned`` boolean column with default 0 / False and index.
Idempotent so greenfield and migrated databases upgrade cleanly.

Revision ID: 0015_add_notes_pinned
Revises: 0014_neutralize_profile_columns
Create Date: 2026-11-16 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

revision: str = "0015_add_notes_pinned"
down_revision: Union[str, None] = "0014_neutralize_profile_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector() -> sa.Inspector | None:
    """Returns an inspector, or None in offline mode."""
    if context.is_offline_mode():
        return None
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {"notes"}

    if "notes" in tables:
        cols = {c["name"] for c in insp.get_columns("notes")} if insp is not None else set()
        if "pinned" not in cols:
            with op.batch_alter_table("notes", recreate="auto") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "pinned",
                        sa.Boolean(),
                        nullable=False,
                        server_default="0",
                    )
                )
                batch_op.create_index("ix_notes_pinned", ["pinned"])


def downgrade() -> None:
    insp = _inspector()
    tables = set(insp.get_table_names()) if insp is not None else {"notes"}

    if "notes" in tables:
        cols = {c["name"] for c in insp.get_columns("notes")} if insp is not None else {"pinned"}
        if "pinned" in cols:
            with op.batch_alter_table("notes", recreate="auto") as batch_op:
                batch_op.drop_index("ix_notes_pinned")
                batch_op.drop_column("pinned")
