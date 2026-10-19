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

"""Layer 5: Scoped Vault HKDF sub-keys isolation conformance test (Step C2e)."""

from __future__ import annotations

import os
from typing import Any, List

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.scope.context import ScopeAccessDeniedError, scope_context
from yarvelle_core.vault.dek import (
    ScopedVault,
    derive_scope_dek,
    get_or_create_dek,
    get_vault_for_scope,
)
from yarvelle_core.vault.errors import DecryptionError


class Layer05VaultTest(BaseIsolationLayerTest):
    """Verifies cryptographic sub-key isolation and cross-scope decryption denial."""

    layer = IsolationLayer.VAULT

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
        kek = runner.kek

        async with runner.session_factory() as session:
            raw_dek, dek_version = await get_or_create_dek(session, profile_id, kek)

        # 1. Assert mathematical distinction between derived keys
        dek_a = derive_scope_dek(raw_dek, scope_a)
        dek_b = derive_scope_dek(raw_dek, scope_b)

        if scope_a != scope_b and dek_a == dek_b:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="key_derivation",
                    details=f"Derived DEK for '{scope_a}' and '{scope_b}' are identical (no HKDF domain separation)",
                )
            )

        # 2. Encrypt secret under pack_b vault, attempt decryption under pack_a vault
        secret_b = pack_b.create_vault_secret(profile_id, scope=scope_b)
        vault_b = ScopedVault(profile_id, scope_b, dek_b, dek_version)
        vault_a = ScopedVault(profile_id, scope_a, dek_a, dek_version)

        ct_b = vault_b.encrypt(secret_b, connection_id="conn-test-1")

        try:
            decrypted = vault_a.decrypt(ct_b, connection_id="conn-test-1")
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack=pack_a.pack_id,
                    target_pack=pack_b.pack_id,
                    target_scope=scope_b,
                    operation="cross_scope_decrypt",
                    details=f"Vault for '{scope_a}' successfully decrypted ciphertext produced under '{scope_b}'",
                    evidence=decrypted[:8],
                )
            )
        except DecryptionError:
            # Expected behavior: GCM tag mismatch / HKDF key separation
            pass

        # 3. Assert get_vault_for_scope enforces caller's ambient ScopeContext
        async with runner.session_factory() as session:
            with scope_context(
                profile_id=profile_id,
                pack_id=pack_a.pack_id,
                scope=scope_a,
                granted_scopes=set(pack_a.owned_scopes),
                pack_declared_scopes=set(pack_a.owned_scopes),
            ):
                try:
                    await get_vault_for_scope(session, profile_id, scope=scope_b, kek=kek)
                    violations.append(
                        LayerViolation(
                            layer=self.layer,
                            source_pack=pack_a.pack_id,
                            target_pack=pack_b.pack_id,
                            target_scope=scope_b,
                            operation="get_vault_for_scope",
                            details=f"get_vault_for_scope allowed retrieving vault for ungranted scope '{scope_b}'",
                        )
                    )
                except ScopeAccessDeniedError:
                    # Expected behavior: ScopeContext authorization gate blocked request
                    pass

        # 4. Verify backwards compatibility for 'health'
        if derive_scope_dek(raw_dek, "health") != raw_dek:
            violations.append(
                LayerViolation(
                    layer=self.layer,
                    source_pack="health",
                    target_pack="health",
                    target_scope="health",
                    operation="health_backward_compat",
                    details="derive_scope_dek('health') does not match raw profile DEK",
                )
            )

        return violations


__all__ = ["Layer05VaultTest"]
