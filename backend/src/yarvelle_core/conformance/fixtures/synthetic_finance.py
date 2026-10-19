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

"""Synthetic finance pack fixture for cross-scope conformance testing (Step C2e)."""

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


class SyntheticFinanceAccount(Base, ScopedMixin):
    """Synthetic financial account ORM model demonstrating scoped table isolation."""

    __tablename__ = "conformance_test_finance_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    institution: Mapped[str] = mapped_column(String(128), nullable=False)
    account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    balance_cents: Mapped[int] = mapped_column(Integer, nullable=False)


async def _execute_list_accounts(args: Dict[str, Any] = None, ctx: Any = None) -> ToolResult:
    return ToolResult(
        success=True,
        output={"accounts": [{"id": "acc-1", "balance": 15420.00}]},
    )


SYNTHETIC_FINANCE_TOOL = ToolSpec(
    name="mock_finance_list_accounts",
    description="List financial accounts for testing",
    risk_tier="read",
    data_flows=DataFlows(),
    scopes={"finance.accounts"},
    executor=_execute_list_accounts,
)


def _check_finance_scope() -> None:
    try:
        require_scope("finance.accounts", level="read")
    except Exception as exc:
        raise HTTPException(
            status_code=403,
            detail=f"Scope grant 'finance.accounts:read' required: {exc}",
        ) from exc


synthetic_finance_router = APIRouter(prefix="/test-finance", tags=["test_finance"])


@synthetic_finance_router.get("/accounts", dependencies=[Depends(_check_finance_scope)])
async def list_mock_accounts():
    return {"status": "ok", "accounts": [{"institution": "MockBank", "balance": 15420}]}


class SyntheticFinancePackFixture:
    """Fixture simulating an isolated finance domain pack."""

    pack_id: str = "test_finance"
    domain: str = "finance"
    owned_scopes: List[str] = ["finance.accounts", "finance.transactions"]
    declared_reads: List[str] = ["alpha.records"]

    def create_orm_record(
        self, session: Any, profile_id: str, scope: str = "finance.accounts"
    ) -> SyntheticFinanceAccount:
        return SyntheticFinanceAccount(
            id=f"acc-{profile_id[:8]}",
            profile_id=profile_id,
            scope=scope,
            institution="First Synthetic Bank",
            account_number="1234-5678-9012",
            balance_cents=1542000,
        )

    def create_cas_file(
        self, cas_root: Any, profile_id: str, scope: str = "finance.accounts"
    ) -> Tuple[str, bytes]:
        content = b"SYNTHETIC BANK STATEMENT: Checking Balance $15,420.00"
        sha = hashlib.sha256(content).hexdigest()
        return sha, content

    def create_search_document(
        self, profile_id: str, scope: str = "finance.accounts"
    ) -> Tuple[str, str]:
        return "doc-fin-001", "Synthetic statement: Mortgage loan balance $320,000 at 4.5% interest"

    def create_memory_entry(
        self, profile_id: str, scope: str = "finance.accounts"
    ) -> Tuple[str, str]:
        return f"scope:{scope}/profile:{profile_id}/working", "User requested monthly savings budget calculation"

    def create_vault_secret(
        self, profile_id: str, scope: str = "finance.accounts"
    ) -> bytes:
        return b"FINANCE_ACCESS_TOKEN_SECRET_KEY_99881122"

    def get_test_tool(self) -> ToolSpec:
        return SYNTHETIC_FINANCE_TOOL

    def get_test_router(self) -> APIRouter:
        return synthetic_finance_router

    def get_exportable_dossier(
        self, profile_id: str, scope: str = "finance.accounts"
    ) -> Dict[str, Any]:
        return {
            "domain": "finance",
            "scope": scope,
            "profile_id": profile_id,
            "accounts": [{"institution": "First Synthetic Bank", "balance": 15420.00}],
        }


__all__ = [
    "SyntheticFinanceAccount",
    "SYNTHETIC_FINANCE_TOOL",
    "synthetic_finance_router",
    "SyntheticFinancePackFixture",
]
