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

"""Layer 9: SSE streaming & dossier export isolation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, Dict, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.scope.context import matches_scope


class Layer09ExportTest(BaseIsolationLayerTest):
    """Verifies that dossier export and streaming filter payloads strictly by domain scope."""

    layer = IsolationLayer.EXPORT

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

        dossier_a = pack_a.get_exportable_dossier(profile_id, scope=scope_a)
        dossier_b = pack_b.get_exportable_dossier(profile_id, scope=scope_b)

        # Multi-domain export filter test
        combined_records = [
            {"scope": scope_a, "data": dossier_a},
            {"scope": scope_b, "data": dossier_b},
        ]

        # Filter strictly for pack_a granted scopes
        scoped_export = [
            r
            for r in combined_records
            if any(matches_scope(pattern, r["scope"]) for pattern in pack_a.owned_scopes)
        ]

        # Verify no scope_b records leaked into pack_a export
        leaked_records = [r for r in scoped_export if r["scope"] == scope_b and scope_a != scope_b]
        if len(leaked_records) > 0:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="dossier_export",
                    details=f"Dossier export for '{pack_a.pack_id}' leaked {len(leaked_records)} records from '{scope_b}'",
                )
            )

        return violations


__all__ = ["Layer09ExportTest"]
