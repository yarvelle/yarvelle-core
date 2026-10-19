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

"""Synthetic alpha pack fixture for cross-scope conformance testing."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from yarvelle_core.db.models import Base
from yarvelle_core.engine.tool_registry import DataFlows, ToolSpec
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.scope.context import require_scope
from yarvelle_core.scope.mixin import ScopedMixin


class SyntheticAlphaRecord(Base, ScopedMixin):
    """Synthetic alpha ORM model demonstrating scoped table isolation."""

    __tablename__ = "conformance_test_alpha_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(String(512), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


async def _execute_get_record(args: Dict[str, Any] = None, ctx: Any = None) -> ToolResult:
    return ToolResult(
        success=True,
        output={"record": {"id": "rec-1", "title": "Alpha Primary Record"}},
    )


SYNTHETIC_ALPHA_TOOL = ToolSpec(
    name="mock_alpha_get_record",
    description="Retrieve alpha records for testing",
    risk_tier="read",
    data_flows=DataFlows(),
    scopes={"alpha.main"},
    executor=_execute_get_record,
)


def _check_alpha_scope() -> None:
    try:
        require_scope("alpha.main", level="read")
    except Exception as exc:
        raise HTTPException(
            status_code=403,
            detail=f"Scope grant 'alpha.main:read' required: {exc}",
        ) from exc


synthetic_alpha_router = APIRouter(prefix="/test-alpha", tags=["test_alpha"])


@synthetic_alpha_router.get("/records", dependencies=[Depends(_check_alpha_scope)])
async def list_mock_records():
    return {"status": "ok", "records": [{"id": "rec-1", "title": "Alpha Record"}]}


class SyntheticAlphaPackFixture:
    """Fixture simulating an isolated alpha domain pack."""

    pack_id: str = "test_alpha"
    domain: str = "alpha"
    owned_scopes: List[str] = ["alpha.main", "alpha.records"]
    declared_reads: List[str] = ["finance.accounts"]

    def create_orm_record(
        self, session: Any, profile_id: str, scope: str = "alpha.records"
    ) -> SyntheticAlphaRecord:
        return SyntheticAlphaRecord(
            id=f"rec-{profile_id[:8]}",
            profile_id=profile_id,
            scope=scope,
            title="Synthetic Alpha Note",
            content="Alpha domain confidential payload for isolation verification",
            priority=2,
        )

    def create_cas_file(
        self, cas_root: Any, profile_id: str, scope: str = "alpha.records"
    ) -> Tuple[str, bytes]:
        content = b"SYNTHETIC ALPHA ATTACHMENT: Confidential Domain Dossier"
        sha = hashlib.sha256(content).hexdigest()
        return sha, content

    def create_search_document(
        self, profile_id: str, scope: str = "alpha.records"
    ) -> Tuple[str, str]:
        return "doc-alpha-001", "Synthetic alpha document: Operational procedures and inventory logs"

    def create_memory_entry(
        self, profile_id: str, scope: str = "alpha.records"
    ) -> Tuple[str, str]:
        return f"scope:{scope}/profile:{profile_id}/working", "User requested alpha project status report"

    def create_vault_secret(
        self, profile_id: str, scope: str = "alpha.records"
    ) -> bytes:
        return b"ALPHA_VAULT_ENCRYPTED_SIGNING_KEY_33445566"

    def get_test_tool(self) -> ToolSpec:
        return SYNTHETIC_ALPHA_TOOL

    def get_test_router(self) -> APIRouter:
        return synthetic_alpha_router

    def get_exportable_dossier(
        self, profile_id: str, scope: str = "alpha.records"
    ) -> Dict[str, Any]:
        return {
            "domain": "alpha",
            "scope": scope,
            "profile_id": profile_id,
            "records": [{"id": "rec-1", "title": "Alpha Record"}],
        }


__all__ = [
    "SyntheticAlphaRecord",
    "SYNTHETIC_ALPHA_TOOL",
    "synthetic_alpha_router",
    "SyntheticAlphaPackFixture",
]
