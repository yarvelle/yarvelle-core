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

"""Declarative base class for Yarvelle Core relational database models."""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy import MetaData, Table, event
from sqlalchemy.orm import DeclarativeBase, Mapper


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models in Yarvelle Core."""

    pass


def ensure_table_comments(table: Table, cls_doc: Optional[str] = None) -> None:
    """Ensure a SQLAlchemy Table, all its Columns, and all its Indexes carry semantic comments.

    Synchronizes Python-level ``Column.doc`` with SQL DDL ``Column.comment``, populates
    ``Table.comment`` from explicit ``__table_args__`` or class docstrings, and attaches
    descriptive ``comment`` metadata to every ``Index`` for dynamic query planning.
    """
    if not table.comment and cls_doc:
        cleaned_doc = " ".join(cls_doc.strip().split())
        if cleaned_doc:
            table.comment = cleaned_doc
    if not table.comment:
        table.comment = f"Relational table '{table.name}' managed by Yarvelle Core."

    for col in table.columns:
        if col.doc and not col.comment:
            col.comment = col.doc
        elif col.comment and not col.doc:
            col.doc = col.comment
        elif not col.comment and not col.doc:
            fk_targets = [fk.target_fullname for fk in col.foreign_keys]
            if col.primary_key:
                default_desc = f"Primary key identifier for {table.name}.{col.name}."
            elif fk_targets:
                default_desc = f"Foreign key referencing {', '.join(fk_targets)}."
            else:
                default_desc = f"Column '{col.name}' ({col.type}) on table '{table.name}'."
            col.comment = default_desc
            col.doc = default_desc

    for idx in table.indexes:
        existing = idx.info.get("comment") or getattr(idx, "comment", None)
        if not existing:
            col_names = [c.name for c in idx.columns]
            col_list_str = ", ".join(col_names)
            uniqueness = "Unique B-tree index" if idx.unique else "B-tree index"
            col_summaries = [
                f"{c.name}: {c.comment}" for c in idx.columns if getattr(c, "comment", None)
            ]
            summary_suffix = f" ({'; '.join(col_summaries)})" if col_summaries else ""
            existing = (
                f"{uniqueness} '{idx.name}' on {table.name}({col_list_str}) "
                f"accelerating equality lookup, range filtering, and ordering{summary_suffix}."
            )
        idx.info["comment"] = existing
        setattr(idx, "comment", existing)


def ensure_metadata_comments(metadata: Optional[MetaData] = None) -> None:
    """Synchronize table, column, and index comments across all tables in metadata."""
    target_meta = metadata or Base.metadata
    for table in target_meta.tables.values():
        ensure_table_comments(table)


@event.listens_for(Base, "instrument_class", propagate=True)
def _on_instrument_class(mapper: Mapper[Any], cls: type[Any]) -> None:
    """Automatically synchronize DDL and ORM comments whenever a model class is registered."""
    local_table = getattr(cls, "__table__", None)
    if isinstance(local_table, Table):
        ensure_table_comments(local_table, getattr(cls, "__doc__", None))

