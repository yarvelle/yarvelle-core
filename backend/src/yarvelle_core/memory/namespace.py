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

"""Canonical memory namespace helper utilities for scoped domain isolation (Step C2c)."""

from __future__ import annotations

from typing import Optional, Tuple

from yarvelle_core.scope.context import DEFAULT_SCOPE


def build_memory_namespace(
    scope: str = DEFAULT_SCOPE,
    profile_id: str = "default",
    sub_namespace: str = "default",
    tier: Optional[str] = None,
) -> str:
    """Builds a canonical scope-prefixed memory namespace.

    Format:
        scope:<scope>/profile:<profile_id>/<subnamespace>
    """
    clean_scope = str(scope).strip() or DEFAULT_SCOPE
    clean_pid = str(profile_id).strip() or "default"
    clean_sub = str(tier or sub_namespace).strip() or "default"
    return f"scope:{clean_scope}/profile:{clean_pid}/{clean_sub}"


def parse_memory_namespace(namespace: str) -> Tuple[Optional[str], Optional[str], str]:
    """Parses scope, profile_id, and subnamespace from a memory namespace string.

    Returns:
        Tuple of (scope, profile_id, sub_namespace).
    """
    if not namespace or not namespace.startswith("scope:"):
        return None, None, namespace

    parts = namespace.split("/", 2)
    scope = parts[0][len("scope:") :].strip() if len(parts) > 0 else None
    profile_id = (
        parts[1][len("profile:") :].strip()
        if len(parts) > 1 and parts[1].startswith("profile:")
        else None
    )
    sub = parts[2].strip() if len(parts) > 2 else "default"
    return scope, profile_id, sub


__all__ = [
    "build_memory_namespace",
    "parse_memory_namespace",
]
