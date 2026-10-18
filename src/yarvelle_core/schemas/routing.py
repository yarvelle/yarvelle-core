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

"""Domain routing and intent classification hints."""

from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field


class RoutingHints(BaseModel):
    """Declarative routing hints contributed by domain packs for orchestrator classification."""

    domain: str
    description: str
    default_agent: str
    domains_info: Dict[str, str] = Field(default_factory=dict)
    patterns_resource: Optional[str] = None
