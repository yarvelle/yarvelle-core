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

"""Search index adapter implementations for SQLite FTS5 and Spector Cognitive Search."""

from __future__ import annotations

from yarvelle_core.search.adapters.spector import SpectorSearchIndex
from yarvelle_core.search.adapters.sqlite import SqliteSearchIndex

__all__ = ["SpectorSearchIndex", "SqliteSearchIndex"]
