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

"""Layer 2: Scoped CAS filesystem storage isolation test (Step C2e)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.storage.cas import get_cas_path, store_cas_file, read_cas_file


class Layer02CasTest(BaseIsolationLayerTest):
    """Verifies that CAS storage partitions by scope and enforces zero cross-scope file access."""

    layer = IsolationLayer.CAS

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
        cas_root = runner.cas_root

        # 1. Store pack_b file in CAS
        sha_b, content_b = pack_b.create_cas_file(cas_root, profile_id, scope=scope_b)
        stored_path_b, _, _ = store_cas_file(
            content=content_b,
            yarvelle_home=cas_root,
            user_id=user_id,
            profile_id=profile_id,
            scope=scope_b,
        )

        # Assert partitioned layout on disk: <cas_root>/<user_id>/<profile_id>/<scope_b>/<sha_b>
        expected_path_b = get_cas_path(cas_root, user_id, profile_id, sha_b, scope=scope_b)
        if stored_path_b != expected_path_b:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="path_layout",
                    details=f"Stored CAS path '{stored_path_b}' does not match partitioned path '{expected_path_b}'",
                )
            )

        # 2. Attempt cross-scope read from pack_a scope
        try:
            read_bytes = read_cas_file(
                yarvelle_home=cas_root,
                user_id=user_id,
                profile_id=profile_id,
                sha256_hash=sha_b,
                scope=scope_a,
            )
            if read_bytes == content_b:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="cross_scope_read",
                        details=f"Pack '{pack_a.pack_id}' was able to read content stored under '{scope_b}' using scope '{scope_a}'",
                    )
                )
        except FileNotFoundError:
            # Expected behavior: file is isolated in scope_b directory
            pass

        # 3. Test scoped deduplication: identical bytes under scope_a must produce distinct file
        shared_bytes = b"STRICTLY_ISOLATED_CROSS_DOMAIN_PAYLOAD_TEST_9988"
        path_a, _, _ = store_cas_file(
            content=shared_bytes,
            yarvelle_home=cas_root,
            user_id=user_id,
            profile_id=profile_id,
            scope=scope_a,
        )
        path_b, _, _ = store_cas_file(
            content=shared_bytes,
            yarvelle_home=cas_root,
            user_id=user_id,
            profile_id=profile_id,
            scope=scope_b,
        )
        if path_a == path_b:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="deduplication",
                    details="CAS deduplicated identical content across distinct scopes into a single physical path",
                )
            )

        return violations


__all__ = ["Layer02CasTest"]
