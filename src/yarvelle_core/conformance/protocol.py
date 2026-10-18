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

"""Contract protocol for packs participating in conformance isolation tests."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Tuple


class ConformancePackProtocol(Protocol):
    """Protocol satisfied by domain packs and fixtures in conformance testing."""

    pack_id: str
    domain: str
    owned_scopes: List[str]
    declared_reads: List[str]

    def create_orm_record(self, session: Any, profile_id: str, scope: str) -> Any: ...
    def create_cas_file(self, cas_root: Any, profile_id: str, scope: str) -> Tuple[str, bytes]: ...
    def create_search_document(self, profile_id: str, scope: str) -> Tuple[str, str]: ...
    def create_memory_entry(self, profile_id: str, scope: str) -> Tuple[str, str]: ...
    def create_vault_secret(self, profile_id: str, scope: str) -> bytes: ...
    def get_test_tool(self) -> Any: ...
    def get_test_router(self) -> Any: ...
    def get_exportable_dossier(self, profile_id: str, scope: str) -> Dict[str, Any]: ...


__all__ = ["ConformancePackProtocol"]
