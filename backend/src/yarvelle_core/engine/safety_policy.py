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

"""Domain-neutral SafetyPolicy protocol and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Sequence, Set, runtime_checkable


@dataclass(frozen=True)
class SafetyVerdict:
    """Standardized verdict returned by input and output safety checks."""

    refused: bool
    reason: Optional[str] = None
    safe_response: Optional[str] = None
    category: Optional[str] = None
    is_hard: bool = False


@dataclass
class EmergencyDirective:
    """Directive generated when acute life-threatening emergency symptoms are detected."""

    detected: bool
    category: str
    trigger_phrase: str
    referral_message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "category": self.category,
            "trigger_phrase": self.trigger_phrase,
            "referral_message": self.referral_message,
        }


@dataclass
class SafetyContext:
    """Contextual metadata passed into safety evaluations."""

    profile_id: Optional[str] = None
    agent_id: Optional[str] = None
    domain: Optional[str] = None
    risk_class: Optional[str] = None
    allow_clinical: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SafetyPolicy(Protocol):
    """Domain-neutral protocol governing pre- and post-execution agent safety."""

    def check_input(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates user input for forbidden intents or dangerous instructions."""
        ...

    def check_output(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates model generation for policy violations or boundary crossing."""
        ...

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        """Checks for acute red flags requiring immediate emergency diversion."""
        ...

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        """Generates the mandatory system prompt safety preamble."""
        ...

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        """Retrieves safe refusal response text for a given refusal reason."""
        ...

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        """Determines whether a refusal requires complete content suppression (Tier 1)."""
        ...

    def get_forbidden_intents(self) -> Set[str]:
        """Returns registered forbidden intent identifier strings."""
        ...


_DEFAULT_SAFETY_POLICY: Optional[SafetyPolicy] = None
_DOMAIN_SAFETY_POLICIES: Dict[str, SafetyPolicy] = {}


def get_default_safety_policy() -> SafetyPolicy:
    """Resolves default safety policy, falling back to NeutralSafetyPolicy."""
    global _DEFAULT_SAFETY_POLICY
    if _DEFAULT_SAFETY_POLICY is None:
        _DEFAULT_SAFETY_POLICY = NeutralSafetyPolicy()
    return _DEFAULT_SAFETY_POLICY


def set_default_safety_policy(policy: SafetyPolicy) -> None:
    """Sets global default safety policy."""
    global _DEFAULT_SAFETY_POLICY
    _DEFAULT_SAFETY_POLICY = policy


def set_domain_safety_policy(domain: str, policy: SafetyPolicy) -> None:
    """Registers a domain-specific safety policy."""
    _DOMAIN_SAFETY_POLICIES[domain] = policy


def get_domain_safety_policy(domain: str) -> Optional[SafetyPolicy]:
    """Retrieves a domain-specific safety policy."""
    return _DOMAIN_SAFETY_POLICIES.get(domain)


class NeutralSafetyPolicy:
    """Baseline domain-neutral safety policy (no-op safety rules)."""

    def check_input(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return SafetyVerdict(refused=False)

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return SafetyVerdict(refused=False)

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        return None

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        return ""

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        return "I cannot fulfill this request as it violates safety guidelines."

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        return True

    def get_forbidden_intents(self) -> Set[str]:
        return set()


class UnionSafetyPolicy:
    """Composite safety policy aggregating multiple SafetyPolicy instances via union logic (ADR 0001 §2.11)."""

    def __init__(self, policies: Optional[Sequence[SafetyPolicy]] = None) -> None:
        self.policies: List[SafetyPolicy] = list(policies or [])

    def add_policy(self, policy: SafetyPolicy) -> None:
        """Adds a policy to the union if not already present."""
        if policy not in self.policies:
            self.policies.append(policy)

    def check_output(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates output across all constituent policies with hard refusal precedence."""
        refused_verdicts: List[tuple[SafetyVerdict, SafetyPolicy]] = []
        for policy in self.policies:
            verdict = policy.check_output(text, ctx)
            if verdict.refused:
                refused_verdicts.append((verdict, policy))

        if not refused_verdicts:
            return SafetyVerdict(refused=False)

        # Hard refusal takes precedence
        for v, p in refused_verdicts:
            if v.is_hard or p.is_hard_refusal_reason(v.reason):
                return SafetyVerdict(
                    refused=True,
                    reason=v.reason,
                    safe_response=v.safe_response,
                    category=v.category,
                    is_hard=True,
                )

        first_v, _ = refused_verdicts[0]
        return SafetyVerdict(
            refused=True,
            reason=first_v.reason,
            safe_response=first_v.safe_response,
            category=first_v.category,
            is_hard=False,
        )

    def check_input(
        self, text: Optional[str], ctx: Optional[SafetyContext] = None
    ) -> SafetyVerdict:
        """Evaluates input across all constituent policies with hard refusal precedence."""
        refused_verdicts: List[tuple[SafetyVerdict, SafetyPolicy]] = []
        for policy in self.policies:
            verdict = policy.check_input(text, ctx)
            if verdict.refused:
                refused_verdicts.append((verdict, policy))

        if not refused_verdicts:
            return SafetyVerdict(refused=False)

        for v, p in refused_verdicts:
            if v.is_hard or p.is_hard_refusal_reason(v.reason):
                return SafetyVerdict(
                    refused=True,
                    reason=v.reason,
                    safe_response=v.safe_response,
                    category=v.category,
                    is_hard=True,
                )

        first_v, _ = refused_verdicts[0]
        return SafetyVerdict(
            refused=True,
            reason=first_v.reason,
            safe_response=first_v.safe_response,
            category=first_v.category,
            is_hard=False,
        )

    def check_emergency(self, text: Optional[str]) -> Optional[EmergencyDirective]:
        """Returns the first detected emergency directive across all policies."""
        for policy in self.policies:
            directive = policy.check_emergency(text)
            if directive is not None and getattr(directive, "detected", False):
                return directive
        return None

    def get_preamble(self, agent: Any, skills: Sequence[Any] = ()) -> str:
        """Concatenates non-empty safety preambles from all policies."""
        preambles = [p.get_preamble(agent, skills) for p in self.policies]
        return "\n\n".join(filter(None, preambles))

    def get_refusal_template(self, reason: Optional[str] = None) -> str:
        """Retrieves the first matching refusal template."""
        for policy in self.policies:
            tmpl = policy.get_refusal_template(reason)
            if tmpl:
                return tmpl
        return "I cannot fulfill this request as it violates safety guidelines."

    def is_hard_refusal_reason(self, reason: Optional[str]) -> bool:
        """Returns True if any constituent policy considers the reason hard."""
        return any(p.is_hard_refusal_reason(reason) for p in self.policies)

    def get_forbidden_intents(self) -> Set[str]:
        """Returns the union of forbidden intents across all policies."""
        intents: Set[str] = set()
        for p in self.policies:
            intents.update(p.get_forbidden_intents())
        return intents


__all__ = [
    "EmergencyDirective",
    "NeutralSafetyPolicy",
    "SafetyContext",
    "SafetyPolicy",
    "SafetyVerdict",
    "UnionSafetyPolicy",
    "get_default_safety_policy",
    "get_domain_safety_policy",
    "set_default_safety_policy",
    "set_domain_safety_policy",
]
