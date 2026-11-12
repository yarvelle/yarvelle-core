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

"""Test-support utilities shipped with yarvelle-core.

Nothing in this package runs automatically. Each subpackage documents how it
is opted into. Shared async DB/entity/HTTP client factories are lazily
re-exported from :mod:`yarvelle_core.testing.fixtures`.
"""

from __future__ import annotations

from typing import Any

_FIXTURE_EXPORTS = {
    "ConnectionFactory",
    "ProfileFactory",
    "SQLStatementCounter",
    "UserFactory",
    "async_db_engine_and_factory",
    "async_db_session",
    "auth_client",
    "count_sql_statements",
    "create_auth_client",
    "create_test_session_factory",
}


def __getattr__(name: str) -> Any:
    if name in _FIXTURE_EXPORTS:
        from yarvelle_core.testing import fixtures

        return getattr(fixtures, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted(_FIXTURE_EXPORTS)
