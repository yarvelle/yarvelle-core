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

"""Guard audit hooks.

Every guard evaluation produces one :class:`GuardAuditRecord`: stage,
outcome, reason, per-check decisions, latencies and model labels. Records
never hold the checked text (only its length), the user's message or the
model's reply. Hooks are called in order; a failing hook is logged and does
not change the verdict.

By default each record is logged as ``safety_guard_evaluated``.
"""

from __future__ import annotations

from typing import Callable, List, Sequence

from yarvelle_core.engine.guards.types import GuardAuditRecord
from yarvelle_core.logging import get_logger

logger = get_logger("yarvelle_core.engine.guards")

GuardAuditHook = Callable[[GuardAuditRecord], None]

_HOOKS: List[GuardAuditHook] = []


def add_guard_audit_hook(hook: GuardAuditHook) -> None:
    """Registers a process-wide hook (for example, writing to the audit log)."""
    if hook not in _HOOKS:
        _HOOKS.append(hook)


def remove_guard_audit_hook(hook: GuardAuditHook) -> None:
    if hook in _HOOKS:
        _HOOKS.remove(hook)


def log_guard_record(record: GuardAuditRecord) -> None:
    logger.info(
        "safety_guard_evaluated",
        stage=record.stage,
        refused=record.refused,
        reason=record.reason,
        warn=record.warn,
        text_length=record.text_length,
        duration_ms=round(record.duration_ms, 2),
        checks=[r.to_dict() for r in record.results],
    )


def emit_guard_record(record: GuardAuditRecord, extra_hooks: Sequence[GuardAuditHook] = ()) -> None:
    for hook in [log_guard_record, *_HOOKS, *extra_hooks]:
        try:
            hook(record)
        except Exception as err:
            logger.warning("safety_guard_audit_hook_failed", error=type(err).__name__)


__all__ = ["GuardAuditHook", "add_guard_audit_hook", "emit_guard_record", "log_guard_record", "remove_guard_audit_hook"]
