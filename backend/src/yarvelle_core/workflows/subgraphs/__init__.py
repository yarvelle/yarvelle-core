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

"""Yarvelle Core workflows subgraphs package.

Houses encapsulated LangGraph subgraphs for:
- Specialist Multi-Agent Supervisor Subgraph (F-33)
- Document Extraction & Attachment Ingestion Subgraph (Phase4 / R2)
"""

from __future__ import annotations

from yarvelle_core.workflows.subgraphs.supervisor import (
    DEFAULT_SPECIALISTS,
    SPECIALIST_BENEFITS_GUIDE,
    SPECIALIST_DOCUMENT_EXTRACTOR,
    SPECIALIST_GENERALIST,
    SPECIALIST_HABIT_COMPANION,
    SPECIALIST_VISIT_STEWARD,
    build_supervisor_subgraph,
    create_supervisor_router_node,
    create_supervisor_subgraph,
    route_specialist_return,
    route_supervisor,
)

__all__ = [
    "DEFAULT_SPECIALISTS",
    "SPECIALIST_BENEFITS_GUIDE",
    "SPECIALIST_DOCUMENT_EXTRACTOR",
    "SPECIALIST_GENERALIST",
    "SPECIALIST_HABIT_COMPANION",
    "SPECIALIST_VISIT_STEWARD",
    "build_supervisor_subgraph",
    "create_supervisor_router_node",
    "create_supervisor_subgraph",
    "route_specialist_return",
    "route_supervisor",
]
