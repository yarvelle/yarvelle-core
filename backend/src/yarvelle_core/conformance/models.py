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

"""Data models for domain-scope conformance verification (Step C2e)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class IsolationLayer(str, Enum):
    ORM = "01_orm"
    CAS = "02_cas"
    FTS5 = "03_fts5"
    MEMORY = "04_memory"
    VAULT = "05_vault"
    TOOL_GATE = "06_tool_gate"
    PROMPT = "07_prompt"
    API = "08_api"
    EXPORT = "09_export"
    AUDIT = "10_audit"
    REDACTION = "11_redaction"


@dataclass(frozen=True)
class LayerViolation:
    layer: IsolationLayer
    source_pack: str
    target_pack: str
    target_scope: str
    operation: str
    details: str
    evidence: Optional[Any] = None


@dataclass
class ConformanceResult:
    passed: bool
    layer_results: Dict[IsolationLayer, bool] = field(default_factory=dict)
    violations: List[LayerViolation] = field(default_factory=list)
    tested_pairs: List[Tuple[str, str]] = field(default_factory=list)


__all__ = [
    "IsolationLayer",
    "LayerViolation",
    "ConformanceResult",
]
