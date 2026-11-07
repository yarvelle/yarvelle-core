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

"""Value types shared by guard checks, the runner and audit hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class GuardDecision(str, Enum):
    """What one check concluded about one text."""

    ALLOW = "allow"
    BLOCK = "block"
    ABSTAIN = "abstain"  # not sure, or the text is outside what the check can cover
    ERROR = "error"  # timeout, failed call, unreadable reply
    SKIPPED = "skipped"  # no model configured for an optional check


# Reason prefixes produced by guards. Every one except the warn prefix is a
# hard refusal: the answer is replaced, never shown.
REASON_BLOCK = "guard"
REASON_WARN = "guard_warn"
REASON_UNAVAILABLE = "guard_unavailable"
REASON_ABSTAINED = "guard_abstained"
HARD_REASON_PREFIXES: Tuple[str, ...] = (f"{REASON_BLOCK}:", f"{REASON_UNAVAILABLE}:", f"{REASON_ABSTAINED}:")


def is_guard_reason(reason: Optional[str]) -> bool:
    return bool(reason) and (str(reason).startswith(HARD_REASON_PREFIXES) or str(reason).startswith(f"{REASON_WARN}:"))


def is_hard_guard_reason(reason: Optional[str]) -> bool:
    return bool(reason) and str(reason).startswith(HARD_REASON_PREFIXES)


@dataclass(frozen=True)
class GuardRequest:
    """The text to check. ``prompt`` is the user's message when checking an answer."""

    stage: str
    text: str
    prompt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardResult:
    """One check's verdict. ``detail`` is a short code, never the checked text."""

    check_id: str
    decision: GuardDecision
    mode: str = "enforce"
    category: Optional[str] = None
    categories: Tuple[str, ...] = ()
    detail: Optional[str] = None
    latency_ms: float = 0.0
    model: Optional[str] = None
    score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "decision": self.decision.value,
            "mode": self.mode,
            "category": self.category,
            "categories": list(self.categories),
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 2),
            "model": self.model,
            "score": self.score,
        }


@dataclass(frozen=True)
class GuardOutcome:
    """The combined verdict for one text.

    ``refused`` replaces the answer. ``warn`` keeps it and marks a boundary
    warning. ``results`` holds every check that ran, shadow checks included.
    """

    refused: bool
    reason: Optional[str] = None
    category: Optional[str] = None
    warn: bool = False
    results: Tuple[GuardResult, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.refused


@dataclass(frozen=True)
class GuardAuditRecord:
    """What a guard audit hook receives. Holds no checked text, only its length."""

    stage: str
    refused: bool
    reason: Optional[str]
    warn: bool
    text_length: int
    results: Tuple[GuardResult, ...]
    duration_ms: float
    source: str = "guards"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "refused": self.refused,
            "reason": self.reason,
            "warn": self.warn,
            "text_length": self.text_length,
            "duration_ms": round(self.duration_ms, 2),
            "source": self.source,
            "results": [r.to_dict() for r in self.results],
            "metadata": dict(self.metadata),
        }


__all__ = [
    "GuardAuditRecord",
    "GuardDecision",
    "GuardOutcome",
    "GuardRequest",
    "GuardResult",
    "HARD_REASON_PREFIXES",
    "REASON_ABSTAINED",
    "REASON_BLOCK",
    "REASON_UNAVAILABLE",
    "REASON_WARN",
    "is_guard_reason",
    "is_hard_guard_reason",
]
