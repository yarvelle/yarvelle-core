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

"""``GuardedSafetyPolicy``: a ``SafetyPolicy`` with guard checks after it.

The wrapped (base) policy always decides first. If it refuses, its verdict
is returned unchanged and no guard runs. Otherwise the guards run, and they
can only add a refusal (or a boundary warning). With no checks for a stage,
the wrapper returns exactly what the base policy returns.

Model checks are asynchronous. Graph nodes and the service call
``acheck_input`` / ``acheck_output`` (through
``yarvelle_core.engine.safety_policy.acheck_output``). A synchronous
``check_output`` runs the base policy and rules checks; if an enforced model
check applies and no verdict for the same text is cached, it refuses with
``guard_unavailable:sync_call`` rather than release an unchecked text.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Union

import yaml

from yarvelle_core.engine.guards.audit import GuardAuditHook
from yarvelle_core.engine.guards.env import env_only_checks
from yarvelle_core.engine.guards.model_check import ModelCheck, ModelFactory
from yarvelle_core.engine.guards.rules import RuleCheck
from yarvelle_core.engine.guards.runner import GuardRunner, aggregate
from yarvelle_core.engine.guards.types import (
    REASON_UNAVAILABLE,
    GuardDecision,
    GuardOutcome,
    GuardRequest,
    is_guard_reason,
    is_hard_guard_reason,
)
from yarvelle_core.engine.safety_policy import (
    EmergencyDirective,
    SafetyContext,
    SafetyPolicy,
    SafetyVerdict,
)
from yarvelle_core.schemas.safety import GuardCheckSpec, SafetyGuardsSpec

ResourceReader = Callable[[str], str]

DEFAULT_GUARD_REFUSAL = "I can't share that response because it did not pass the safety checks."
SYNC_CALL_REASON = f"{REASON_UNAVAILABLE}:sync_call"


class GuardConfigError(ValueError):
    """Guard configuration could not be turned into checks."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _call_base(fn: Callable[..., SafetyVerdict], text: Optional[str], ctx: Optional[SafetyContext]) -> SafetyVerdict:
    # Same call shape as before guards existed: ctx only when one is given.
    return fn(text, ctx) if ctx is not None else fn(text)


class GuardedSafetyPolicy:
    """Runs a base ``SafetyPolicy``, then guard checks that can only add refusals."""

    def __init__(
        self,
        base: SafetyPolicy,
        runner: GuardRunner,
        *,
        refusal_template: Optional[str] = None,
        includes_env: bool = False,
        cache_size: int = 64,
    ) -> None:
        self.base = base
        self.runner = runner
        self.refusal_template = refusal_template
        self.includes_env = includes_env
        self._cache: "OrderedDict[tuple[str, str], GuardOutcome]" = OrderedDict()
        self._cache_size = max(0, int(cache_size))
        self._lock = threading.Lock()

    # -- delegated protocol members ------------------------------------
    def __getattr__(self, name: str) -> Any:
        # Pack-specific helpers on the base policy stay reachable.
        if name in ("base", "runner"):
            raise AttributeError(name)
        return getattr(self.base, name)

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        return self.base.check_emergency(text)

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return self.base.get_preamble(agent, skills)

    def get_forbidden_intents(self) -> Set[str]:
        return self.base.get_forbidden_intents()

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        if is_guard_reason(reason) and self.refusal_template:
            return self.refusal_template
        tmpl = self.base.get_refusal_template(reason)
        return tmpl or DEFAULT_GUARD_REFUSAL

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        if is_guard_reason(reason):
            return is_hard_guard_reason(reason)
        return self.base.is_hard_refusal_reason(reason)

    # -- verdicts -------------------------------------------------------
    def _verdict(self, outcome: GuardOutcome) -> SafetyVerdict:
        if outcome.refused:
            return SafetyVerdict(
                refused=True,
                reason=outcome.reason,
                safe_response=self.get_refusal_template(outcome.reason),
                category=outcome.category,
                is_hard=True,
            )
        if outcome.warn:
            return SafetyVerdict(refused=True, reason=outcome.reason, category=outcome.category, is_hard=False)
        return SafetyVerdict(refused=False)

    def _cache_get(self, stage: str, text: str) -> Optional[GuardOutcome]:
        if not self._cache_size:
            return None
        key = (stage, _hash(text))
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _cache_put(self, stage: str, text: str, outcome: GuardOutcome) -> None:
        if not self._cache_size:
            return
        # Errors and missing models are not cached, so the next call retries.
        if any(r.decision in (GuardDecision.ERROR, GuardDecision.SKIPPED) for r in outcome.results):
            return
        key = (stage, _hash(text))
        with self._lock:
            self._cache[key] = outcome
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def _sync(self, stage: str, text: Optional[str]) -> SafetyVerdict:
        body = text or ""
        if not body or not self.runner.applies(stage):
            return SafetyVerdict(refused=False)
        cached = self._cache_get(stage, body)
        if cached is not None:
            return self._verdict(cached)
        request = GuardRequest(stage=stage, text=body)
        outcome = aggregate(self.runner.evaluate_rules_sync(request), self.runner.specs)
        if outcome.refused or not self.runner.needs_model(stage):
            return self._verdict(outcome)
        return SafetyVerdict(
            refused=True,
            reason=SYNC_CALL_REASON,
            safe_response=self.get_refusal_template(SYNC_CALL_REASON),
            category="guard_unavailable",
            is_hard=True,
        )

    async def _async(self, stage: str, text: Optional[str], ctx: Optional[SafetyContext]) -> SafetyVerdict:
        body = text or ""
        if not body or not self.runner.applies(stage):
            return SafetyVerdict(refused=False)
        cached = self._cache_get(stage, body)
        if cached is not None:
            return self._verdict(cached)
        meta: Dict[str, Any] = dict(getattr(ctx, "metadata", None) or {})
        if ctx is not None and ctx.agent_id:
            meta.setdefault("agent_id", ctx.agent_id)
        prompt = meta.pop("prompt", None)
        request = GuardRequest(stage=stage, text=body, prompt=str(prompt) if prompt else None, metadata=meta)
        outcome = await self.runner.evaluate(request)
        self._cache_put(stage, body, outcome)
        return self._verdict(outcome)

    def check_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        verdict = _call_base(self.base.check_input, text, ctx)
        return verdict if verdict.refused else self._sync("input", text)

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        verdict = _call_base(self.base.check_output, text, ctx)
        return verdict if verdict.refused else self._sync("output", text)

    async def acheck_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        from yarvelle_core.engine.safety_policy import acheck_input

        verdict = await acheck_input(self.base, text, ctx)
        return verdict if verdict.refused else await self._async("input", text, ctx)

    async def acheck_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        from yarvelle_core.engine.safety_policy import acheck_output

        verdict = await acheck_output(self.base, text, ctx)
        return verdict if verdict.refused else await self._async("output", text, ctx)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _pack_reader(pack: Any) -> Optional[ResourceReader]:
    from yarvelle_core.resources.pack_resolver import (
        PackResourceResolver,
        prefixes_for_pack,
        resolve_pack_root,
    )

    root = resolve_pack_root(pack)
    if root is None:
        return None
    resolver = PackResourceResolver(
        pack.id,
        Path(root),
        allowed_prefixes=prefixes_for_pack(getattr(pack, "provides", None), getattr(pack, "routing_hints", None)),
    )
    return resolver.read_text


def _guards_of(pack: Any) -> Optional[SafetyGuardsSpec]:
    safety = getattr(pack, "safety", None)
    return getattr(safety, "guards", None) if safety is not None else None


def build_checks(
    specs: Sequence[GuardCheckSpec],
    *,
    resource_reader: Optional[ResourceReader] = None,
    chat_models: Optional[Mapping[str, Any]] = None,
    model_factory: Optional[ModelFactory] = None,
) -> list:
    """Compiles check specs. Configuration errors raise ``GuardConfigError``."""
    chat_models = dict(chat_models or {})
    checks: list = []
    for spec in specs:
        try:
            if spec.type == "rules":
                extra: Dict[str, Any] = {}
                if spec.rules_file:
                    if resource_reader is None:
                        raise GuardConfigError(f"check '{spec.id}': rules_file needs a pack root to read from")
                    loaded = yaml.safe_load(resource_reader(spec.rules_file)) or {}
                    if not isinstance(loaded, dict):
                        raise GuardConfigError(f"check '{spec.id}': rules_file must hold a mapping")
                    extra = loaded
                check: Any = RuleCheck(spec, extra)
            else:
                template = None
                if spec.prompt_file:
                    if resource_reader is None:
                        raise GuardConfigError(f"check '{spec.id}': prompt_file needs a pack root to read from")
                    template = resource_reader(spec.prompt_file)
                check = ModelCheck(
                    spec,
                    chat_model=chat_models.get(spec.id),
                    model_factory=model_factory,
                    prompt_template=template,
                )
        except GuardConfigError:
            raise
        except Exception as err:
            raise GuardConfigError(f"guard check '{spec.id}' is invalid: {err}") from err
        checks.append(check)
    return checks


def build_guarded_policy(
    base: SafetyPolicy,
    guards: Union[SafetyGuardsSpec, Mapping[str, Any], None] = None,
    *,
    pack: Any = None,
    resource_reader: Optional[ResourceReader] = None,
    chat_models: Optional[Mapping[str, Any]] = None,
    model_factory: Optional[ModelFactory] = None,
    extra_checks: Sequence[Any] = (),
    include_env: bool = True,
    audit_hooks: Sequence[GuardAuditHook] = (),
) -> SafetyPolicy:
    """Wraps ``base`` with guard checks. Returns ``base`` itself when there are none.

    ``guards`` defaults to ``pack.safety.guards``. ``rules_file`` and
    ``prompt_file`` are read through ``resource_reader`` or, when a pack with
    a filesystem root is given, its contained resource resolver.
    ``chat_models`` maps check ids to ready chat models (skips the factory).
    ``extra_checks`` are Python checks (see ``GuardCheck``). With
    ``include_env``, checks named in ``<PREFIX>_SAFETY_GUARDS`` are added.
    """
    if guards is None and pack is not None:
        guards = _guards_of(pack)
    spec = SafetyGuardsSpec.model_validate(guards) if isinstance(guards, Mapping) else guards
    spec = spec or SafetyGuardsSpec()
    if resource_reader is None and pack is not None:
        resource_reader = _pack_reader(pack)
    specs = list(spec.checks)
    if include_env:
        specs.extend(env_only_checks([c.id for c in specs] + [c.id for c in extra_checks]))
    checks = build_checks(specs, resource_reader=resource_reader, chat_models=chat_models, model_factory=model_factory)
    checks.extend(extra_checks)
    runner = GuardRunner(checks, deadline_s=spec.deadline_s, audit_hooks=audit_hooks)
    if not runner.checks:
        return base
    return GuardedSafetyPolicy(base, runner, refusal_template=spec.refusal_template, includes_env=include_env)


def apply_env_guards(policy: SafetyPolicy) -> SafetyPolicy:
    """Adds env-only checks (``<PREFIX>_SAFETY_GUARDS``) once. Unchanged when unset."""
    from yarvelle_core import identity
    from yarvelle_core.engine.guards.env import ENV_GUARDS

    if not identity.getenv(ENV_GUARDS):
        return policy
    current: Any = policy
    while isinstance(current, GuardedSafetyPolicy):
        if current.includes_env:
            return policy
        current = current.base
    return build_guarded_policy(policy, SafetyGuardsSpec(), include_env=True)


__all__ = [
    "DEFAULT_GUARD_REFUSAL",
    "GuardConfigError",
    "GuardedSafetyPolicy",
    "SYNC_CALL_REASON",
    "apply_env_guards",
    "build_checks",
    "build_guarded_policy",
]
