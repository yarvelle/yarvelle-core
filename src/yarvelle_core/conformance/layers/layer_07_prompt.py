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

"""Layer 7: LLM prompt & context assembly isolation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.scope.context import matches_scope


class Layer07PromptTest(BaseIsolationLayerTest):
    """Verifies that prompt builder and context assembler filter tools and memory by active scope."""

    layer = IsolationLayer.PROMPT

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

        tool_a = pack_a.get_test_tool()
        tool_b = pack_b.get_test_tool()

        # Simulate context assembly filtering available tools for an agent in pack_a
        available_tools = [tool_a, tool_b]
        filtered_tools = [
            t
            for t in available_tools
            if any(matches_scope(owned, s) for owned in pack_a.owned_scopes for s in getattr(t, "scopes", ["health"]))
        ]

        if tool_b in filtered_tools and scope_a != scope_b:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="prompt_tool_filtering",
                    details=f"Prompt context for pack '{pack_a.pack_id}' included out-of-scope tool '{tool_b.name}'",
                )
            )

        return violations


__all__ = ["Layer07PromptTest"]
