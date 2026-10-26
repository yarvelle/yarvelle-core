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

"""Output refusal guardrail and compliance disclaimer node (F-27).

Inspects generated model completion. If unauthorized advice or prohibited intent
is detected, sets refusal flag and routes to self-correction reflection.
Appends compliance disclaimers to valid responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union
from langchain_core.messages import AIMessage

from yarvelle_core.engine.safety_policy import (
    SafetyPolicy,
    UnionSafetyPolicy,
    get_default_safety_policy,
    get_domain_safety_policy,
)
from yarvelle_core.resources.loader import get_resource_loader
from yarvelle_core.workflows.nodes.base import BaseNode


class OutputGuardrailNode(BaseNode):
    """Verifies output safety and appends compliance disclaimers across safety policies."""

    def __init__(
        self,
        name: str = "output_guardrail",
        safety_policy: Optional[Union[SafetyPolicy, Sequence[SafetyPolicy]]] = None,
    ) -> None:
        super().__init__(name=name)
        if isinstance(safety_policy, (list, tuple)):
            self.safety_policy: SafetyPolicy = UnionSafetyPolicy(safety_policy)
        else:
            self.safety_policy = safety_policy or get_default_safety_policy()

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Checks output text against refusal boundaries."""
        output_text = state.get("output", "")
        if not output_text:
            messages: List[Any] = state.get("messages", [])
            for m in reversed(messages):
                msg_type = getattr(m, "type", "")
                if msg_type in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")):
                    break
                if isinstance(m, AIMessage) and getattr(m, "content", ""):
                    output_text = str(getattr(m, "content", "") or "")
                    break
                elif isinstance(m, dict) and m.get("role") in ("assistant", "ai") and m.get("content"):
                    output_text = str(m.get("content", ""))
                    break

        # Dynamically aggregate union policy across state-provided policies and participating panel domains
        policies: List[SafetyPolicy] = [self.safety_policy]
        extra_policies = state.get("safety_policies") or []
        if isinstance(extra_policies, (list, tuple)):
            for p in extra_policies:
                if p not in policies:
                    policies.append(p)
        participating_domains = set(state.get("participating_domains") or [])
        if not participating_domains and state.get("deliberation_state"):
            d_state = state["deliberation_state"]
            for prop in (d_state.get("active_proposals") or {}).values():
                scope = prop.get("scope") if isinstance(prop, dict) else getattr(prop, "scope", None)
                if scope:
                    participating_domains.add(scope)
        for dom in participating_domains:
            dom_pol = get_domain_safety_policy(dom)
            if dom_pol and dom_pol not in policies:
                policies.append(dom_pol)

        effective_policy = UnionSafetyPolicy(policies) if len(policies) > 1 else policies[0]
        safety_check = effective_policy.check_output(output_text)

        # Safety refusal gate
        if safety_check.refused:
            reason = safety_check.reason or "forbidden_intent:policy_prohibited"
            is_hard = effective_policy.is_hard_refusal_reason(reason)
            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": reason,
                "boundary_warning": not is_hard,
                "boundary_reason": reason if not is_hard else None,
                "next_step": "reflection",
                "is_compliant": False,
                "compliance_metadata": {
                    "compliant": False,
                    "reason": reason,
                    "boundary_warning": not is_hard,
                },
            }

        # Tier 2 (Soft Boundary Notice) and Compliant Output:
        # Preserve full output text, clean robotic preambles, and append compliance disclaimer.
        import re
        pattern = r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)[,:]?(?:\*|_){0,2}[,:]?\s*)"
        cleaned_output = re.sub(pattern, "", output_text.lstrip(), flags=re.IGNORECASE).lstrip("*_ \t")
        if cleaned_output and cleaned_output != output_text:
            cleaned_output = cleaned_output[0].upper() + cleaned_output[1:] if len(cleaned_output) > 1 else cleaned_output.upper()
            output_text = cleaned_output

        # Appends standard compliance disclaimer
        loader = get_resource_loader()
        header_text = loader.get_disclaimer_header_text()
        disclaimer_clause = f"\n\n*Disclaimer: {header_text}*"

        final_output = output_text
        if header_text and header_text.lower() not in output_text.lower():
            final_output = f"{output_text}{disclaimer_clause}"

        boundary_warning = bool(safety_check.refused and not effective_policy.is_hard_refusal_reason(safety_check.reason))
        boundary_reason = safety_check.reason if boundary_warning else None

        return {
            "is_refusal": False,
            "refused": False,
            "boundary_warning": boundary_warning,
            "boundary_reason": boundary_reason,
            "is_compliant": True,
            "output": final_output,
            "compliance_disclaimer": header_text,
            "disclaimer": header_text,
            "compliance_metadata": {
                "compliant": True,
                "has_disclaimer": True,
                "boundary_warning": boundary_warning,
                "boundary_reason": boundary_reason,
            },
            "next_step": "suggestion",
        }



__all__ = ["OutputGuardrailNode"]
