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

"""Unit tests for SqliteSearchIndex FTS5 scoped search."""

from __future__ import annotations

from pathlib import Path
import pytest

from yarvelle_core.search.adapters.sqlite import SqliteSearchIndex


@pytest.mark.asyncio
async def test_sqlite_search_index_scoped_search(tmp_path: Path):
    db_path = tmp_path / "search.db"
    idx = SqliteSearchIndex(db_path=str(db_path))

    await idx.index_document(
        document_id="doc_alpha",
        text="Alpha secret property tax records for 2026",
        metadata={"domain": "alpha"},
        profile_id="pid_1",
        scope="alpha.main",
    )
    await idx.index_document(
        document_id="doc_finance",
        text="Finance monthly checking account statement with interest",
        metadata={"domain": "finance"},
        profile_id="pid_1",
        scope="finance.accounts",
    )

    # Query 'records' in alpha scope -> 1 hit
    alpha_hits = await idx.search("records", profile_id="pid_1", scope="alpha.main")
    assert len(alpha_hits) == 1
    assert alpha_hits[0].document_id == "doc_alpha"

    # Query 'statement' targeting alpha scope -> 0 hits
    leak_hits = await idx.search("statement", profile_id="pid_1", scope="alpha.main")
    assert len(leak_hits) == 0

    # Query 'statement' targeting finance scope -> 1 hit
    fin_hits = await idx.search("statement", profile_id="pid_1", scope="finance.accounts")
    assert len(fin_hits) == 1
    assert fin_hits[0].document_id == "doc_finance"

    await idx.close()
