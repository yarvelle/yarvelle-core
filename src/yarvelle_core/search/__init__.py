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

"""Hexagonal cognitive search subsystem for Yarvelle Core: ports, chunkers, adapters, and factory."""

from __future__ import annotations

from yarvelle_core.search.adapters.spector import SpectorSearchIndex
from yarvelle_core.search.adapters.sqlite import SqliteSearchIndex
from yarvelle_core.search.base import SearchIndex, SearchResult
from yarvelle_core.search.chunker import (
    Chunker,
    ClinicalChunk,
    ClinicalChunker,
    DocumentChunk,
    StructuralChunker,
)
from yarvelle_core.search.factory import (
    SEARCH_BACKEND_SPECTOR,
    SEARCH_BACKEND_SQLITE,
    SUPPORTED_SEARCH_BACKENDS,
    create_search_index,
    get_search_index,
    is_spector_reachable,
    reset_search_index,
    reset_search_indexes,
    set_search_index,
)

__all__ = [
    "Chunker",
    "ClinicalChunk",
    "ClinicalChunker",
    "DocumentChunk",
    "SEARCH_BACKEND_SPECTOR",
    "SEARCH_BACKEND_SQLITE",
    "SUPPORTED_SEARCH_BACKENDS",
    "SearchIndex",
    "SearchResult",
    "SpectorSearchIndex",
    "SqliteSearchIndex",
    "StructuralChunker",
    "create_search_index",
    "get_search_index",
    "is_spector_reachable",
    "reset_search_index",
    "reset_search_indexes",
    "set_search_index",
]
