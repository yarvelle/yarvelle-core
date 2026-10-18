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

"""Unit tests for DocumentChunk and StructuralChunker."""

from __future__ import annotations

import pytest

from yarvelle_core.search.chunker import Chunker, DocumentChunk, StructuralChunker


def test_structural_chunker_implements_protocol():
    chunker = StructuralChunker()
    assert isinstance(chunker, Chunker)


def test_structural_chunker_partitions_sections():
    chunker = StructuralChunker(min_tokens=10, max_tokens=50, overlap_tokens=5)
    sample_text = """# Header 1
First paragraph with several descriptive sentences regarding household tasks.

# Header 2
Second paragraph detailing family schedule and school appointments.
"""
    chunks = chunker.chunk("doc-1", sample_text)
    assert len(chunks) >= 2
    for c in chunks:
        assert isinstance(c, DocumentChunk)
        assert c.token_count > 0
        assert c.chunk_id.startswith("doc-1#")
