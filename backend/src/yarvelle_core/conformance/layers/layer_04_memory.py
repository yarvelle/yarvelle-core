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

"""Layer 4: Scoped Memory namespace isolation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.memory.namespace import build_memory_namespace, parse_memory_namespace
from yarvelle_core.memory.ports import MemoryTier
from yarvelle_core.scope.context import scope_context


class Layer04MemoryTest(BaseIsolationLayerTest):
    """Verifies that MemoryPort enforces namespace prefixing and cross-scope recall denial."""

    layer = IsolationLayer.MEMORY

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
        memory_port = runner.memory_port

        # 1. Verify canonical namespace format
        ns_b = build_memory_namespace(profile_id=profile_id, scope=scope_b, tier="working")
        parsed_scope, parsed_pid, parsed_sub = parse_memory_namespace(ns_b)
        if parsed_scope != scope_b or parsed_pid != profile_id:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="namespace_parse",
                    details=f"Memory namespace '{ns_b}' failed canonical parsing (got scope={parsed_scope}, pid={parsed_pid})",
                )
            )

        # 2. Store memory under pack_b namespace
        key_b, content_b = pack_b.create_memory_entry(profile_id, scope=scope_b)
        await memory_port.remember(
            key=key_b,
            value=content_b,
            tier=MemoryTier.WORKING,
            namespace=ns_b,
        )

        # 3. In pack_a context, attempt to recall memory targeting pack_b's namespace
        with scope_context(
            profile_id=profile_id,
            pack_id=pack_a.pack_id,
            scope=scope_a,
            granted_scopes=set(pack_a.owned_scopes),
            pack_declared_scopes=set(pack_a.owned_scopes),
        ):
            try:
                recalled = await memory_port.recall(
                    query="monthly savings budget calculation",
                    tier=MemoryTier.WORKING,
                    namespace=ns_b,
                )
                if len(recalled) > 0:
                    violations.append(
                        LayerViolation(
                            layer=self.layer,
                            source_pack=pack_a.pack_id,
                            target_pack=pack_b.pack_id,
                            target_scope=scope_b,
                            operation="memory_recall",
                            details=f"Pack '{pack_a.pack_id}' was able to recall memory from '{ns_b}'",
                            evidence=[
                                str(r.get("value") if isinstance(r, dict) else getattr(r, "value", r))
                                for r in recalled
                            ],
                        )
                    )
            except PermissionError:
                # Expected behavior: memory adapter caught cross-scope namespace read
                pass

        return violations


__all__ = ["Layer04MemoryTest"]
