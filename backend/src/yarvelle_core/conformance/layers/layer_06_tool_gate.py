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

"""Layer 6: ToolExecutionGate scope validation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.scope.context import scope_context


class Layer06ToolGateTest(BaseIsolationLayerTest):
    """Verifies that ToolExecutionGate blocks invocations targeting out-of-scope tools."""

    layer = IsolationLayer.TOOL_GATE

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

        tool_b = pack_b.get_test_tool()
        tool_a = pack_a.get_test_tool()

        ctx = ToolContext(
            user_id=user_id,
            profile_id=profile_id,
            run_id="run-conformance-1",
        )

        # 1. Attempt to execute pack_b's tool under pack_a's scope context
        with scope_context(
            profile_id=profile_id,
            pack_id=pack_a.pack_id,
            scope=scope_a,
            granted_scopes=set(pack_a.owned_scopes),
            pack_declared_scopes=set(pack_a.owned_scopes),
        ):
            res_b = await execute_tool_call(ctx, tool_b, {})
            if res_b.success:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="execute_unauthorized_tool",
                        details=f"Tool '{tool_b.name}' succeeded under pack '{pack_a.pack_id}' scope context",
                    )
                )

        # 2. Execute pack_a's tool under pack_a's scope context -> should succeed
        with scope_context(
            profile_id=profile_id,
            pack_id=pack_a.pack_id,
            scope=scope_a,
            granted_scopes=set(pack_a.owned_scopes),
            pack_declared_scopes=set(pack_a.owned_scopes),
        ):
            res_a = await execute_tool_call(ctx, tool_a, {})
            if not res_a.success and "SecurityViolation" in str(res_a.error):
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_a.pack_id,
                        target_scope=scope_a,
                        operation="execute_authorized_tool",
                        details=f"Authorized tool '{tool_a.name}' was incorrectly rejected by ToolExecutionGate: {res_a.error}",
                    )
                )

        return violations


__all__ = ["Layer06ToolGateTest"]
