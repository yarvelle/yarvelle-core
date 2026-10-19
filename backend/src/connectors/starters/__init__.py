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

"""Built-in starter connectors and dynamic pack starter resolution."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

# Extend __path__ with installed pack starter directories so submodule imports
# like `from connectors.starters.zocdoc import ...` resolve natively.
try:
    _spec = importlib.util.find_spec("carefold_health")
    if _spec and _spec.submodule_search_locations:
        for _loc in _spec.submodule_search_locations:
            _pack_starters = Path(_loc) / "connectors" / "starters"
            if _pack_starters.is_dir() and str(_pack_starters) not in __path__:
                __path__.append(str(_pack_starters))
except Exception:
    pass

from connectors.starters.calendar import (
    CalDavConnector,
    GoogleCalendarConnector,
    sanitize_calendar_event_title,
    suggest_free_slots,
)


def __getattr__(name: str) -> Any:
    if name == "EpicSmartConnector":
        mod = importlib.import_module("connectors.starters.epic_smart")
        return mod.EpicSmartConnector
    if name == "WithingsConnector":
        mod = importlib.import_module("connectors.starters.withings")
        return mod.WithingsConnector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CalDavConnector",
    "EpicSmartConnector",
    "GoogleCalendarConnector",
    "WithingsConnector",
    "sanitize_calendar_event_title",
    "suggest_free_slots",
]
