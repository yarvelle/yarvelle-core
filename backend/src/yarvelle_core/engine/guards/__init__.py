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

"""Configurable safety guard checks that run after a pack's ``SafetyPolicy``.

Core provides the plumbing: check types (regex rules, model checks through
LangChain chat models), verdict aggregation where policy and rule refusals
always win, abstain/timeout/error handling that fails closed, a guard audit
hook and environment-variable configuration. Packs provide the rules,
prompts, labels and thresholds; users choose and run any models. Core ships
no model and no domain vocabulary.

See ``docs/safety-guards.md``.
"""

from yarvelle_core.engine.guards.audit import (
    GuardAuditHook,
    add_guard_audit_hook,
    remove_guard_audit_hook,
)
from yarvelle_core.engine.guards.env import GuardEnvError, guard_env_name
from yarvelle_core.engine.guards.model_check import ModelCheck, ModelCheckConfigError
from yarvelle_core.engine.guards.policy import (
    GuardConfigError,
    GuardedSafetyPolicy,
    apply_env_guards,
    build_checks,
    build_guarded_policy,
)
from yarvelle_core.engine.guards.release import has_guards, resolve_output_release
from yarvelle_core.engine.guards.rules import RuleCheck, RulesConfigError
from yarvelle_core.engine.guards.runner import GuardCheck, GuardRunner, aggregate
from yarvelle_core.engine.guards.types import (
    GuardAuditRecord,
    GuardDecision,
    GuardOutcome,
    GuardRequest,
    GuardResult,
    is_guard_reason,
    is_hard_guard_reason,
)

__all__ = [
    "GuardAuditHook",
    "GuardAuditRecord",
    "GuardCheck",
    "GuardConfigError",
    "GuardDecision",
    "GuardEnvError",
    "GuardOutcome",
    "GuardRequest",
    "GuardResult",
    "GuardRunner",
    "GuardedSafetyPolicy",
    "ModelCheck",
    "ModelCheckConfigError",
    "RuleCheck",
    "RulesConfigError",
    "add_guard_audit_hook",
    "aggregate",
    "apply_env_guards",
    "build_checks",
    "build_guarded_policy",
    "guard_env_name",
    "has_guards",
    "is_guard_reason",
    "is_hard_guard_reason",
    "remove_guard_audit_hook",
    "resolve_output_release",
]
