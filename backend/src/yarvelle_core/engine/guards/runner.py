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

"""Runs guard checks for one text and combines their verdicts.

Order and precedence:

1. ``rules`` checks run first. An enforced rules block ends the evaluation:
   model checks are not called, because no model verdict can undo it.
2. ``model`` checks run concurrently. Each has its own timeout and all of
   them share ``deadline_s``; a check still running at the deadline is
   cancelled and counts as an error.
3. Only ``enforce`` checks count. ``shadow`` checks run and are audited.

Combined verdict (first matching line wins):

- an enforced block with ``on_block: refuse``      -> refuse ``guard:<id>:<category>``
- abstain (on_abstain block), error (on_error block),
  or unconfigured (when_unconfigured block)         -> refuse ``guard_abstained:<id>`` /
                                                       ``guard_unavailable:<id>``
- an enforced block with ``on_block: warn``          -> keep the answer, ``guard_warn:<id>:<category>``
- otherwise                                         -> allow
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from yarvelle_core.engine.guards.audit import GuardAuditHook, emit_guard_record
from yarvelle_core.engine.guards.types import (
    REASON_ABSTAINED,
    REASON_BLOCK,
    REASON_UNAVAILABLE,
    REASON_WARN,
    GuardAuditRecord,
    GuardDecision,
    GuardOutcome,
    GuardRequest,
    GuardResult,
)
from yarvelle_core.schemas.safety import GuardCheckSpec


class GuardCheck(Protocol):
    """What the runner needs from a check. Packs may supply their own."""

    id: str
    kind: str  # "rules" (deterministic, run first) or "model"
    mode: str  # enforce | shadow
    spec: GuardCheckSpec

    async def evaluate(self, request: GuardRequest) -> GuardResult: ...


def aggregate(results: Sequence[GuardResult], specs: Dict[str, GuardCheckSpec]) -> GuardOutcome:
    """Combines check results into one outcome (see module docstring)."""
    blocks: List[Tuple[str, Optional[str]]] = []
    unavailable: List[str] = []
    warns: List[Tuple[str, Optional[str]]] = []
    for r in results:
        if r.mode != "enforce":
            continue
        spec = specs[r.check_id]
        if r.decision == GuardDecision.BLOCK:
            cat = r.category or "blocked"
            if spec.on_block == "warn":
                warns.append((f"{REASON_WARN}:{r.check_id}:{cat}", cat))
            else:
                blocks.append((f"{REASON_BLOCK}:{r.check_id}:{cat}", cat))
        elif r.decision == GuardDecision.ABSTAIN and spec.on_abstain == "block":
            unavailable.append(f"{REASON_ABSTAINED}:{r.check_id}")
        elif r.decision == GuardDecision.ERROR and spec.on_error == "block":
            unavailable.append(f"{REASON_UNAVAILABLE}:{r.check_id}")
        elif r.decision == GuardDecision.SKIPPED and spec.when_unconfigured == "block":
            unavailable.append(f"{REASON_UNAVAILABLE}:{r.check_id}")
    if blocks:
        reason, cat = blocks[0]
        return GuardOutcome(refused=True, reason=reason, category=cat, results=tuple(results))
    if unavailable:
        return GuardOutcome(refused=True, reason=unavailable[0], category="guard_unavailable", results=tuple(results))
    if warns:
        reason, cat = warns[0]
        return GuardOutcome(refused=False, warn=True, reason=reason, category=cat, results=tuple(results))
    return GuardOutcome(refused=False, results=tuple(results))


class GuardRunner:
    """Evaluates a fixed list of checks for each stage."""

    def __init__(
        self,
        checks: Sequence[Any],
        *,
        deadline_s: float = 20.0,
        audit_hooks: Sequence[GuardAuditHook] = (),
        source: str = "guards",
    ) -> None:
        self.checks = [c for c in checks if getattr(c, "mode", "enforce") != "off"]
        ids = [c.id for c in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate guard check ids: {ids}")
        self.deadline_s = float(deadline_s)
        self.audit_hooks = list(audit_hooks)
        self.source = source
        self.specs: Dict[str, GuardCheckSpec] = {c.id: c.spec for c in self.checks}

    def for_stage(self, stage: str) -> List[Any]:
        return [c for c in self.checks if stage in c.spec.effective_stages()]

    def applies(self, stage: str) -> bool:
        return bool(self.for_stage(stage))

    def needs_model(self, stage: str) -> bool:
        """True when an enforced model check could change this stage's verdict."""
        for c in self.for_stage(stage):
            if c.kind == "rules" or c.mode != "enforce":
                continue
            configured = getattr(c, "configured", True)
            if configured or c.spec.when_unconfigured == "block":
                return True
        return False

    def evaluate_rules_sync(self, request: GuardRequest) -> List[GuardResult]:
        return [c.evaluate_sync(request) for c in self.for_stage(request.stage) if c.kind == "rules"]

    async def evaluate(self, request: GuardRequest) -> GuardOutcome:
        start = time.perf_counter()
        stage_checks = self.for_stage(request.stage)
        rules = [c for c in stage_checks if c.kind == "rules"]
        models = [c for c in stage_checks if c.kind != "rules"]
        results: List[GuardResult] = []
        for check in rules:
            results.append(await check.evaluate(request))
        early = aggregate(results, self.specs)
        if models and not (early.refused and early.reason and early.reason.startswith(f"{REASON_BLOCK}:")):
            results.extend(await self._run_models(models, request))
        outcome = aggregate(results, self.specs)
        self._audit(request, outcome, start)
        return outcome

    async def _run_models(self, models: Sequence[Any], request: GuardRequest) -> List[GuardResult]:
        tasks = {asyncio.ensure_future(c.evaluate(request)): c for c in models}
        try:
            done, pending = await asyncio.wait(tasks.keys(), timeout=self.deadline_s)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        for t in pending:
            t.cancel()
        out: List[GuardResult] = []
        for task, check in tasks.items():
            if task in done and not task.cancelled() and task.exception() is None:
                out.append(task.result())
            else:
                detail = "deadline_exceeded" if task in pending else "check_failed"
                out.append(GuardResult(check_id=check.id, decision=GuardDecision.ERROR, mode=check.mode, detail=detail))
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return out

    def _audit(self, request: GuardRequest, outcome: GuardOutcome, start: float) -> None:
        record = GuardAuditRecord(
            stage=request.stage,
            refused=outcome.refused,
            reason=outcome.reason,
            warn=outcome.warn,
            text_length=len(request.text or ""),
            results=outcome.results,
            duration_ms=(time.perf_counter() - start) * 1000.0,
            source=self.source,
            metadata={k: v for k, v in request.metadata.items() if k in ("agent_id", "thread_id", "run_id")},
        )
        emit_guard_record(record, self.audit_hooks)


__all__ = ["GuardCheck", "GuardRunner", "aggregate"]
