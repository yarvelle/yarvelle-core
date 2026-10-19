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

"""Layer 11: Multi-scope PII sanitization & redaction isolation test (Step C2e)."""

from __future__ import annotations

from typing import Any, List

from yarvelle_core.audit.redaction import redact_audit_event
from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.schemas.audit import AuditEvent


class Layer11RedactionTest(BaseIsolationLayerTest):
    """Verifies that audit event sanitizer scrubs sensitive payloads across domain boundaries."""

    layer = IsolationLayer.REDACTION

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

        # Multi-domain sensitive payload
        sensitive_prompt = (
            f"Transfer funds from bank account 1234-5678-9012 for client ID-998811 "
            f"with SSN 000-12-3456 to pay medical invoice."
        )

        event = AuditEvent(
            agent_id="test-agent",
            event="tool",
            tool=pack_a.get_test_tool().name,
            prompt=sensitive_prompt,
            completion="Transfer confirmed.",
            profile_id=profile_id,
            scope=scope_a,
            pack_id=pack_a.pack_id,
        )

        redacted = redact_audit_event(event, store_bodies=False)

        # Zero-body default invariant: prompt and completion must be stripped
        if redacted.get("prompt") is not None or redacted.get("completion") is not None:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="zero_body_redaction",
                    details="Audit redaction failed to strip sensitive prompt/completion bodies when store_bodies=False",
                )
            )

        return violations


__all__ = ["Layer11RedactionTest"]
