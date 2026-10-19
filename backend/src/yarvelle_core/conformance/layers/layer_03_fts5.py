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

"""Layer 3: Scoped FTS5 search index isolation test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation


class Layer03Fts5Test(BaseIsolationLayerTest):
    """Verifies that FTS5 search index strictly filters search queries by domain scope."""

    layer = IsolationLayer.FTS5

    async def run(
        self,
        runner: Any,
        pack_a: Any,
        pack_b: Any,
        profile_id: str,
        user_id: str,
    ) -> List[LayerViolation]:
        violations: List[LayerViolation] = []
        scope_a = pack_a.owned_scopes[0]
        scope_b = pack_b.owned_scopes[0]
        search_index = runner.search_index

        # 1. Index document for pack_b
        doc_id_b, text_b = pack_b.create_search_document(profile_id, scope=scope_b)
        await search_index.index_document(
            document_id=doc_id_b,
            text=text_b,
            metadata={},
            profile_id=profile_id,
            scope=scope_b,
        )

        # 2. Index document for pack_a
        doc_id_a, text_a = pack_a.create_search_document(profile_id, scope=scope_a)
        await search_index.index_document(
            document_id=doc_id_a,
            text=text_a,
            metadata={},
            profile_id=profile_id,
            scope=scope_a,
        )

        import re

        def _pick_search_token(text: str) -> str:
            for word in text.split():
                clean = re.sub(r"[^a-zA-Z]", "", word)
                if len(clean) >= 5 and clean.lower() not in {
                    "synthetic",
                    "document",
                    "records",
                    "statement",
                    "confidential",
                    "domain",
                    "procedures",
                }:
                    return clean
            return "Mortgage"

        # 3. Search for pack_b keyword while targeting scope_a
        target_b_query = _pick_search_token(text_b)
        b_hits = await search_index.search(
            query=target_b_query,
            profile_id=profile_id,
            scope=scope_a,
            limit=10,
        )
        if len(b_hits) > 0:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="fts5_search",
                    details=f"Querying scope '{scope_a}' returned {len(b_hits)} search hits containing '{scope_b}' data",
                    evidence=[h.document_id for h in b_hits],
                )
            )

        # 4. Search for pack_a keyword targeting scope_a -> verify normal query works
        target_a_query = _pick_search_token(text_a)
        a_hits = await search_index.search(
            query=target_a_query,
            profile_id=profile_id,
            scope=scope_a,
            limit=10,
        )
        if len(a_hits) == 0:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_a.pack_id,
                    target_scope=scope_a,
                    operation="fts5_search_self",
                    details=f"Valid query targeting own scope '{scope_a}' returned 0 hits",
                )
            )

        return violations


__all__ = ["Layer03Fts5Test"]
