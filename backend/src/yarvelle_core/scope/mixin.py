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

"""ScopedMixin declarative ORM mixin enforcing domain scope partitioning."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


class ScopedMixin:
    """Declarative ORM mixin enforcing domain scope partitioning."""

    scope: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="health",
        server_default="health",
        index=True,
        doc="Domain scope partition identifier (e.g. 'health', 'health.records', 'finance.accounts')",
        comment="Domain scope partition identifier isolating records by domain and subdomain namespace.",
    )


__all__ = ["ScopedMixin"]
