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

"""Layer 8: API routing & middleware isolation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.scope.context import scope_context


class Layer08ApiTest(BaseIsolationLayerTest):
    """Verifies that API endpoints enforce scope permissions via require_scope."""

    layer = IsolationLayer.API

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

        app = FastAPI()
        app.include_router(pack_a.get_test_router())
        app.include_router(pack_b.get_test_router())

        client = TestClient(app)
        router_b = pack_b.get_test_router()
        if router_b.routes:
            first_path = router_b.routes[0].path
            route_path = first_path if first_path.startswith(router_b.prefix) else f"{router_b.prefix}{first_path}"
        else:
            route_path = f"{router_b.prefix}/test"

        # 1. Request endpoint B while active in pack A scope
        with scope_context(
            profile_id=profile_id,
            pack_id=pack_a.pack_id,
            scope=scope_a,
            granted_scopes=set(pack_a.owned_scopes),
            pack_declared_scopes=set(pack_a.owned_scopes),
        ):
            resp = client.get(route_path)
            if resp.status_code == 200:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="api_request_denial",
                        details=f"API route '{route_path}' returned 200 OK while caller held only '{scope_a}' grant",
                    )
                )

        # 2. Request endpoint B while active in pack B scope -> should return 200
        with scope_context(
            profile_id=profile_id,
            pack_id=pack_b.pack_id,
            scope=scope_b,
            granted_scopes=set(pack_b.owned_scopes),
            pack_declared_scopes=set(pack_b.owned_scopes),
        ):
            resp_valid = client.get(route_path)
            if resp_valid.status_code != 200:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_b.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="api_request_allow",
                        details=f"API route '{route_path}' failed with status {resp_valid.status_code} despite valid '{scope_b}' grant",
                    )
                )

        return violations


__all__ = ["Layer08ApiTest"]
