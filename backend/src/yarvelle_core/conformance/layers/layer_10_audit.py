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

"""Layer 10: Audit event scope tagging & hash-chaining conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.audit.hash_chain import (
    append_chained_audit_event,
    verify_profile_audit_chain,
)
from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation


class Layer10AuditTest(BaseIsolationLayerTest):
    """Verifies that AuditEventRecord records scope, pack_id, and preserves cryptographic chaining."""

    layer = IsolationLayer.AUDIT

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

        async with runner.session_factory() as session:
            # 1. Append event for pack_a
            ev_a = await append_chained_audit_event(
                session,
                profile_id=profile_id,
                actor_user_id=user_id,
                event="tool",
                tool=pack_a.get_test_tool().name,
                scope=scope_a,
                pack_id=pack_a.pack_id,
            )

            # 2. Append event for pack_b
            ev_b = await append_chained_audit_event(
                session,
                profile_id=profile_id,
                actor_user_id=user_id,
                event="tool",
                tool=pack_b.get_test_tool().name,
                scope=scope_b,
                pack_id=pack_b.pack_id,
            )
            await session.commit()

            # 3. Assert metadata fields are persisted
            if ev_a.scope != scope_a or ev_a.pack_id != pack_a.pack_id:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_a.pack_id,
                        target_scope=scope_a,
                        operation="audit_metadata",
                        details=f"Event A metadata drifted (got scope={ev_a.scope}, pack_id={ev_a.pack_id})",
                    )
                )

            if ev_b.scope != scope_b or ev_b.pack_id != pack_b.pack_id:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_b.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="audit_metadata",
                        details=f"Event B metadata drifted (got scope={ev_b.scope}, pack_id={ev_b.pack_id})",
                    )
                )

            # 4. Verify hash-chain integrity across interleaved events
            verification = await verify_profile_audit_chain(session, profile_id)
            if not verification["valid"]:
                violations.append(
                    LayerViolation(
                        layer=self.layer,
                        source_pack=pack_a.pack_id,
                        target_pack=pack_b.pack_id,
                        target_scope=scope_b,
                        operation="audit_chain_verification",
                        details=f"Audit hash chain broken across interleaved multi-scope events: {verification.get('reason')}",
                    )
                )

        return violations


__all__ = ["Layer10AuditTest"]
