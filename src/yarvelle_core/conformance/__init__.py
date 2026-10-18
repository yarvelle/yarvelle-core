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

"""Scope Conformance Framework.

Provides reusable, 11-layer domain-scope isolation verification across pack pairs.
"""

from yarvelle_core.conformance.models import (
    ConformanceResult,
    IsolationLayer,
    LayerViolation,
)
from yarvelle_core.conformance.protocol import ConformancePackProtocol
from yarvelle_core.conformance.runner import (
    ScopeConformanceRunner,
    run_conformance_matrix,
    run_conformance_matrix_sync,
    run_multi_pack_conformance_matrix,
)

__all__ = [
    "IsolationLayer",
    "LayerViolation",
    "ConformanceResult",
    "ConformancePackProtocol",
    "ScopeConformanceRunner",
    "run_conformance_matrix",
    "run_conformance_matrix_sync",
    "run_multi_pack_conformance_matrix",
]
