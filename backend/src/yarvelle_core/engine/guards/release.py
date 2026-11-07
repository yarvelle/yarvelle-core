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

"""How a turn's answer is released to the client (``safety.guards.release``).

- ``stream`` (default): answer tokens are sent while the answer is generated.
  The ``done`` event carries the final verdict; a client must replace the
  streamed text with ``done.fullText`` when ``done.refused`` is true.
- ``buffered``: no answer token is sent before the final check passes. The
  checked answer is then sent as one token event, followed by ``done``. A
  refused answer is never sent. Progress events (tool, task status, notices)
  still stream.

The strictest source wins: buffered if the pack's guards ask for it, the
service was built with ``output_release="buffered"``, or
``<PREFIX>_SAFETY_OUTPUT_RELEASE=buffered`` is set. Nothing can turn a
pack's buffered release back into streaming.
"""

from __future__ import annotations

from typing import Any, Optional

from yarvelle_core import identity

RELEASE_STREAM = "stream"
RELEASE_BUFFERED = "buffered"
ENV_OUTPUT_RELEASE = "SAFETY_OUTPUT_RELEASE"
_VALUES = (RELEASE_STREAM, RELEASE_BUFFERED)


def _walk(policy: Any, seen: Optional[set] = None):
    """Yields the policy and every policy it wraps or unites."""
    seen = seen if seen is not None else set()
    if policy is None or id(policy) in seen:
        return
    seen.add(id(policy))
    yield policy
    base = policy.__dict__.get("base") if hasattr(policy, "__dict__") else None
    if base is not None:
        yield from _walk(base, seen)
    for member in (policy.__dict__.get("policies") or []) if hasattr(policy, "__dict__") else []:
        yield from _walk(member, seen)


def has_guards(policy: Any) -> bool:
    """True when ``policy`` (or a policy it wraps) carries guard checks."""
    from yarvelle_core.engine.guards.policy import GuardedSafetyPolicy

    return any(isinstance(p, GuardedSafetyPolicy) for p in _walk(policy))


def _check(value: Optional[str], where: str) -> Optional[str]:
    if value is None:
        return None
    norm = str(value).strip().lower()
    if norm not in _VALUES:
        raise ValueError(f"{where} must be 'stream' or 'buffered', got {value!r}")
    return norm


def resolve_output_release(policy: Any, override: Optional[str] = None) -> str:
    """Effective release mode for a service using ``policy`` (see module docstring)."""
    from yarvelle_core.engine.guards.policy import GuardedSafetyPolicy

    sources = [
        _check(override, "output_release"),
        _check(identity.getenv(ENV_OUTPUT_RELEASE), identity.env_name(ENV_OUTPUT_RELEASE)),
    ]
    sources.extend(
        getattr(p, "release", None) for p in _walk(policy) if isinstance(p, GuardedSafetyPolicy)
    )
    return RELEASE_BUFFERED if RELEASE_BUFFERED in sources else RELEASE_STREAM


__all__ = [
    "ENV_OUTPUT_RELEASE",
    "RELEASE_BUFFERED",
    "RELEASE_STREAM",
    "has_guards",
    "resolve_output_release",
]
