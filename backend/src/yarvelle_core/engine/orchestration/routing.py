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

"""Deterministic fixed-route selection, evaluated before any model call.

A pack declares ``orchestration.fixed_routes``; each route names a trigger
(attachments on the turn, or an input-guardrail flag) and the agent that must
take the turn when it fires. Guardrail-flag routes win over attachment routes,
and routes of the same kind are tried in declaration order.
"""

from __future__ import annotations

import mimetypes
from fnmatch import fnmatchcase
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from yarvelle_core.schemas.orchestration import (
    FixedRoute,
    GuardrailFlagTrigger,
    HasAttachmentsTrigger,
    PackOrchestrationSpec,
    RouteDecision,
    RouteSource,
)

_ATTACHMENT_KEYS = ("attachments", "document_dossiers", "document_text", "raw_text")
_MEDIA_TYPE_KEYS = ("mime_type", "content_type", "media_type")

BUILTIN_DOCUMENT_ROUTE_ID = "builtin-documents"
"""Route id recorded when, without pack routes, attachments go to the built-in
document agent."""


def has_attachments(state: Mapping[str, Any]) -> bool:
    """Returns True when the turn carries any attachment or extracted document."""
    return any(bool(state.get(key)) for key in _ATTACHMENT_KEYS)


def attachment_media_types(state: Mapping[str, Any]) -> List[str]:
    """Returns the lower-cased media types declared on the turn's attachments."""
    out: List[str] = []
    for item in state.get("attachments") or ():
        value: Any = None
        if isinstance(item, str):
            value = mimetypes.guess_type(item)[0]
        elif isinstance(item, Mapping):
            value = next((item.get(k) for k in _MEDIA_TYPE_KEYS if item.get(k)), None)
        else:
            value = next((getattr(item, k, None) for k in _MEDIA_TYPE_KEYS if getattr(item, k, None)), None)
        if value:
            out.append(str(value).split(";", 1)[0].strip().lower())
    return out


def raised_guardrail_flags(state: Mapping[str, Any]) -> List[str]:
    """Returns the flags the input guardrail raised for this turn."""
    flags = state.get("guardrail_flags") or ()
    if isinstance(flags, str):
        flags = [flags]
    elif isinstance(flags, Mapping):
        flags = [k for k, v in flags.items() if v]
    return [str(f) for f in flags]


def _media_matches(patterns: Sequence[str], media_types: Iterable[str]) -> bool:
    lowered = [p.lower() for p in patterns]
    return any(fnmatchcase(m, p) for m in media_types for p in lowered)


def _fires(route: FixedRoute, state: Mapping[str, Any], flags: Sequence[str]) -> bool:
    trigger = route.when
    if isinstance(trigger, GuardrailFlagTrigger):
        return trigger.flag in flags
    if isinstance(trigger, HasAttachmentsTrigger):
        if not has_attachments(state):
            return False
        if not trigger.mime_types:
            return True
        return _media_matches(trigger.mime_types, attachment_media_types(state))
    return False


def select_fixed_route(
    spec: Optional[PackOrchestrationSpec],
    state: Mapping[str, Any],
) -> Optional[RouteDecision]:
    """Returns the fixed-route decision for this turn, or None when no route fires."""
    if spec is None or not spec.fixed_routes:
        return None
    flags = raised_guardrail_flags(state)
    ordered = [r for r in spec.fixed_routes if isinstance(r.when, GuardrailFlagTrigger)] + [
        r for r in spec.fixed_routes if isinstance(r.when, HasAttachmentsTrigger)
    ]
    for route in ordered:
        if _fires(route, state, flags):
            return RouteDecision(
                source=RouteSource.FIXED_ROUTE,
                route_id=route.route_id,
                agent_id=route.agent_id,
            )
    return None


__all__ = [
    "BUILTIN_DOCUMENT_ROUTE_ID",
    "attachment_media_types",
    "has_attachments",
    "raised_guardrail_flags",
    "select_fixed_route",
]
