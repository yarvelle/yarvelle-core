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

"""Conformance test pack fixtures."""

from yarvelle_core.conformance.fixtures.synthetic_alpha import (
    SYNTHETIC_ALPHA_TOOL,
    SyntheticAlphaPackFixture,
    SyntheticAlphaRecord,
    synthetic_alpha_router,
)
from yarvelle_core.conformance.fixtures.synthetic_finance import (
    SYNTHETIC_FINANCE_TOOL,
    SyntheticFinanceAccount,
    SyntheticFinancePackFixture,
    synthetic_finance_router,
)

__all__ = [
    "SYNTHETIC_ALPHA_TOOL",
    "SYNTHETIC_FINANCE_TOOL",
    "SyntheticAlphaPackFixture",
    "SyntheticAlphaRecord",
    "SyntheticFinanceAccount",
    "SyntheticFinancePackFixture",
    "synthetic_alpha_router",
    "synthetic_finance_router",
]
