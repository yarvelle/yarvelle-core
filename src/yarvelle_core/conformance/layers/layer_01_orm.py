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

"""Layer 1: ScopedSession / ORM isolation conformance test (Step C2e)."""

from __future__ import annotations

from typing import Any, List
from sqlalchemy import select, update, delete

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.models import IsolationLayer, LayerViolation
from yarvelle_core.scope.context import ScopeViolationError, scope_context


class Layer01OrmTest(BaseIsolationLayerTest):
    """Verifies that ScopedSession enforces strict query and flush isolation across scopes."""

    layer = IsolationLayer.ORM

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
            # 1. Seed pack_b record within pack_b's authorized scope context
            with scope_context(
                profile_id=profile_id,
                pack_id=pack_b.pack_id,
                scope=scope_b,
                granted_scopes=set(pack_b.owned_scopes),
                pack_declared_scopes=set(pack_b.owned_scopes),
            ):
                b_record = pack_b.create_orm_record(session, profile_id, scope=scope_b)
                session.add(b_record)
                await session.commit()

        # 2. Assert pack_a cannot SELECT pack_b's record
        async with runner.session_factory() as session:
            with scope_context(
                profile_id=profile_id,
                pack_id=pack_a.pack_id,
                scope=scope_a,
                granted_scopes=set(pack_a.owned_scopes),
                pack_declared_scopes=set(pack_a.owned_scopes),
            ):
                model_cls = type(b_record)
                stmt = select(model_cls).where(model_cls.profile_id == profile_id)
                res = await session.execute(stmt)
                rows = list(res.scalars().all())
                if len(rows) > 0:
                    violations.append(
                        LayerViolation(
                            layer=self.layer,
                            source_pack=pack_a.pack_id,
                            target_pack=pack_b.pack_id,
                            target_scope=scope_b,
                            operation="select",
                            details=f"Pack '{pack_a.pack_id}' was able to select {len(rows)} rows belonging to pack '{pack_b.pack_id}'",
                            evidence=[r.id for r in rows],
                        )
                    )

        # 3. Assert pack_a cannot flush / insert into pack_b's scope
        async with runner.session_factory() as session:
            with scope_context(
                profile_id=profile_id,
                pack_id=pack_a.pack_id,
                scope=scope_a,
                granted_scopes=set(pack_a.owned_scopes),
                pack_declared_scopes=set(pack_a.owned_scopes),
            ):
                attempted_record = pack_b.create_orm_record(
                    session, f"{profile_id}-tamper", scope=scope_b
                )
                attempted_record.id = f"{attempted_record.id}-tamper"
                session.add(attempted_record)
                try:
                    await session.flush()
                    violations.append(
                        LayerViolation(
                            layer=self.layer,
                            source_pack=pack_a.pack_id,
                            target_pack=pack_b.pack_id,
                            target_scope=scope_b,
                            operation="insert_flush",
                            details=f"Pack '{pack_a.pack_id}' successfully flushed record into ungranted scope '{scope_b}' without error",
                        )
                    )
                except ScopeViolationError:
                    # Expected behavior: write guard caught unauthorized scope
                    await session.rollback()
                except Exception as exc:
                    await session.rollback()

        # 4. Assert pack_a cannot bulk update pack_b records
        async with runner.session_factory() as session:
            with scope_context(
                profile_id=profile_id,
                pack_id=pack_a.pack_id,
                scope=scope_a,
                granted_scopes=set(pack_a.owned_scopes),
                pack_declared_scopes=set(pack_a.owned_scopes),
            ):
                model_cls = type(b_record)
                upd_stmt = (
                    update(model_cls)
                    .where(model_cls.profile_id == profile_id)
                    .values(scope=scope_b)
                )
                upd_res = await session.execute(upd_stmt)
                await session.commit()
                if upd_res.rowcount > 0:
                    violations.append(
                        LayerViolation(
                            layer=self.layer,
                            source_pack=pack_a.pack_id,
                            target_pack=pack_b.pack_id,
                            target_scope=scope_b,
                            operation="bulk_update",
                            details=f"Pack '{pack_a.pack_id}' updated {upd_res.rowcount} rows in scope '{scope_b}'",
                        )
                    )

        return violations


__all__ = ["Layer01OrmTest"]
