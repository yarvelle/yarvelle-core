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

"""Base class for all 11 scope isolation layer tests."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List

from yarvelle_core.conformance.models import IsolationLayer, LayerViolation


class BaseIsolationLayerTest(ABC):
    """Abstract base class for an isolation layer conformance test."""

    layer: IsolationLayer

    @abstractmethod
    async def run(
        self,
        runner: Any,
        pack_a: Any,
        pack_b: Any,
        profile_id: str,
        user_id: str,
    ) -> List[LayerViolation]:
        """Executes isolation verification asserting pack_a cannot observe or corrupt pack_b data."""
        ...


__all__ = ["BaseIsolationLayerTest"]
