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

"""Response synthesis and output coordination node (R3 / F-25).

Consolidates multi-agent specialist outputs and blackboard deliberation state into
a unified coordinated plan, formats resource allocation tables with skipped constraint
notations, summarizes multi-round trade-offs, formats structured minority reports and
open amendment notes, flags untrusted inputs, deduplicates constituent disclaimers,
appends the canonical disclaimer footer, and records zero-body audit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import json
import logging
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Union

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage
from langgraph.store.base import BaseStore

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

from yarvelle_core.audit.logger import _file_lock
from yarvelle_core.audit.redaction import redact_audit_event
from yarvelle_core.config import settings
from yarvelle_core.constants.paths import DEFAULT_AUDIT_LOG_FILE, LOGS_DIR
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager
from yarvelle_core.workflows.nodes.base import BaseNode
from yarvelle_core.workflows.state import CritiqueStance

logger = logging.getLogger(__name__)

CANONICAL_DISCLAIMER = (
    "DISCLAIMER: Yarvelle Core provides educational and administrative navigation assistance, not professional advice. "
    "Verify important decisions with qualified professionals."
)

CONSTITUENT_DISCLAIMER_PATTERNS = [
    re.compile(r"DISCLAIMER:.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"NOTE: I am not an? (?:attorney|advisor|agent).*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"Please consult your (?:advisor|provider) before.*?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\*Disclaimer:.*?\*(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL),
]


class class_or_instance_method:
    """Decorator allowing a method to be called either on an instance or on the class."""

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func
        self.__doc__ = func.__doc__
        self.__name__ = func.__name__

    def __get__(self, instance: Any, owner: Any) -> Callable[..., Any]:
        if instance is not None:
            @wraps(self.func)
            def _bound(state: Dict[str, Any]) -> str:
                return self.func(instance, state)

            return _bound

        @wraps(self.func)
        def _unbound(state: Dict[str, Any]) -> str:
            return self.func(owner(), state)

        return _unbound


class ResponseSynthesizerNode(BaseNode):
    """Discrete node consolidating multi-agent specialist outputs into a coordinated plan."""

    def __init__(
        self,
        name: str = "response_synthesizer",
        model: Optional[BaseChatModel] = None,
    ) -> None:
        super().__init__(name=name)
        self.model = model

    async def __call__(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """LangGraph node execution callable interface supporting store injection."""
        return await self.execute(state, store=store, **kwargs)

    @classmethod
    def strip_reference_preamble(cls, text: str) -> str:
        """Strips robotic 'Based on the provided reference document/guide...' opening phrases."""
        if not text:
            return ""
        pattern = r"^(?:(?:\*|_){0,2}(?:(?:Based on|According to|From) (?:the )?(?:provided )?reference (?:document|guide|material|checklist|information|docs?)(?: provided)?)[,:]?(?:\*|_){0,2}[,:]?\s*)"
        cleaned = re.sub(pattern, "", text.lstrip(), flags=re.IGNORECASE)
        cleaned = cleaned.lstrip("*_ \t")
        if cleaned and cleaned != text:
            cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
        return cleaned

    @classmethod
    def strip_disclaimers(cls, text: str) -> str:
        """Removes constituent agent disclaimers and reference preambles from specialist text."""
        if not text:
            return ""
        cleaned = cls.strip_reference_preamble(text)
        for pat in CONSTITUENT_DISCLAIMER_PATTERNS:
            cleaned = pat.sub("", cleaned).strip()
        cleaned = re.sub(
            r"(?m)^\s*(?:\*|_)?DISCLAIMER:.*(?:\*|_)?\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned

    def synthesize_deliberation(self, state: Dict[str, Any]) -> str:
        """Synthesizes structured multi-agent deliberation state (ADR 0001 §2.11).

        Produces:
        1. Unified plan with generic stakeholder advisory framing.
        2. Constraint resource table with skipped limits explicitly noted.
        3. Trade-offs summary explaining multi-round proposal revisions.
        4. Structured minority report (Option A vs. Option B) for unresolved CONFLICT critiques;
           open amendment notes for unresolved AMEND critiques.
        5. Untrusted-input flags for tainted proposals.
        6. Canonical disclaimer footer.
        """
        delib_state = state.get("deliberation_state") or {}

        # 0. Degraded fallback handling
        if delib_state.get("degraded"):
            missing = delib_state.get("missing_agents") or []
            missing_str = f" Missing agents: {', '.join(missing)}." if missing else ""
            fallback_text = state.get("output") or "Multi-agent deliberation degraded to single-agent answer due to insufficient valid proposals."
            clean_fb = self.strip_disclaimers(str(fallback_text))
            full_out = (
                f"# Deliberation Plan (for stakeholder review)\n\n"
                f"*Note: Multi-agent deliberation degraded to single-agent answer due to insufficient valid proposals.{missing_str}*\n\n"
                f"{clean_fb}\n\n"
                f"{CANONICAL_DISCLAIMER}"
            )
            state["output"] = full_out
            return full_out

        bb = BlackboardManager.from_state_dict(delib_state)
        proposals = bb.active_proposals
        shared_constraints = bb.shared_constraints
        rounds_used = delib_state.get("rounds_used") or (max(bb.proposals.keys()) if bb.proposals else 1)
        skipped_constraints = delib_state.get("skipped_constraints") or []

        # Taint detection
        tainted_props = [p for p in proposals.values() if getattr(p, "tainted", False)]
        run_tainted = bool(state.get("tainted"))

        sections: List[str] = []

        # 1. Unified Coordinated Plan Framing (Generic stakeholder advisory)
        sections.append("# Deliberation Plan (for stakeholder review)\n")
        sections.append(
            "*Draft coordinated plan compiled from multi-specialist deliberation for human review and evaluation. "
            "This proposal is prepared for administrative coordination and does not constitute formal professional or legal advice.*\n"
        )

        # Untrusted-input warning banner
        if tainted_props or run_tainted:
            tainted_ids = [p.agent_id for p in tainted_props]
            if tainted_ids:
                for tid in sorted(tainted_ids):
                    sections.append(
                        f"> ⚠️ **Warning**: Recommendations from agent '{tid}' are based partly on content from an untrusted source.\n"
                    )
            else:
                sections.append(
                    "> ⚠️ **Warning**: Recommendations in this plan are based partly on content from an untrusted source.\n"
                )

        # Active proposals & recommendations
        sections.append("### Consolidated Recommendations\n")
        if proposals:
            for aid, prop in sorted(proposals.items()):
                agent_name = aid.replace("-", " ").replace("_", " ").title()
                taint_tag = " [⚠️ Untrusted Source]" if getattr(prop, "tainted", False) else ""
                sections.append(f"#### {agent_name} Perspective{taint_tag}")
                if prop.summary:
                    clean_sum = self.strip_disclaimers(prop.summary)
                    sections.append(f"- **Summary**: {clean_sum}")
                if prop.recommendations:
                    sections.append("- **Key Recommendations**:")
                    for r in prop.recommendations:
                        sections.append(f"  - {r}")
                if prop.dependencies:
                    deps = ", ".join(prop.dependencies)
                    sections.append(f"- **Dependencies**: {deps}")
                sections.append("")
        else:
            sections.append("No active specialist proposals available.\n")

        # 2. Resource Allocation & Shared Constraints Table
        sections.append("## Resource Allocation & Shared Constraints\n")
        if shared_constraints:
            table_lines = [
                "| Constraint | Limit | Total Claimed | Status |",
                "| :--- | :--- | :--- | :--- |",
            ]
            has_skipped = False
            for c in shared_constraints:
                claimed = sum(p.resource_claims.get(c.id, 0.0) for p in proposals.values())
                unit_suffix = f" {c.unit}" if c.unit else ""
                is_skipped = c.limit_value is None or c.id in skipped_constraints
                if is_skipped:
                    has_skipped = True
                    limit_str = "None (Skipped)"
                    status_str = "Limit Unknown (Skipped)"
                else:
                    src_str = f" ({c.limit_source})" if c.limit_source else ""
                    limit_str = f"{c.limit_value:.1f}{unit_suffix}{src_str}"
                    if claimed - c.limit_value > 1e-9:
                        over = claimed - c.limit_value
                        status_str = f"Overbudget (+{over:.1f})"
                    else:
                        status_str = "Within limit"
                claimed_str = f"{claimed:.1f}{unit_suffix}"
                table_lines.append(f"| {c.id} | {limit_str} | {claimed_str} | {status_str} |")
            sections.append("\n".join(table_lines) + "\n")
            if has_skipped:
                sections.append("*Note: Constraints with unknown limits were not checked against a budget boundary.*\n")
        else:
            sections.append("*No shared resource constraints declared for this panel.*\n")

        # 3. Trade-Offs Summary
        sections.append("## Trade-Offs & Multi-Round Revisions\n")
        revisions: List[str] = []
        if rounds_used > 1 and len(bb.proposals) > 1:
            r1_props = bb.proposals.get(1, {})
            for r in range(2, rounds_used + 1):
                r_props = bb.proposals.get(r, {})
                for aid, prop in sorted(r_props.items()):
                    r1_prop = r1_props.get(aid)
                    if r1_prop:
                        changes: List[str] = []
                        for cid, val in prop.resource_claims.items():
                            old_val = r1_prop.resource_claims.get(cid)
                            if old_val is not None and abs(val - old_val) > 1e-9:
                                if val < old_val:
                                    changes.append(f"reduced `{cid}` allocation from {old_val:.1f} to {val:.1f}")
                                else:
                                    changes.append(f"adjusted `{cid}` allocation from {old_val:.1f} to {val:.1f}")
                        for old_cid, old_val in r1_prop.resource_claims.items():
                            if old_cid not in prop.resource_claims:
                                changes.append(f"removed claim on `{old_cid}` ({old_val:.1f})")
                        if prop.summary != r1_prop.summary and not changes:
                            changes.append("revised recommendations to address peer critique")
                        if changes:
                            revisions.append(f"- **{aid}** revised proposal in Round {r}: {', '.join(changes)}.")
        if revisions:
            sections.append(f"Across {rounds_used} deliberation rounds, panel members negotiated the following trade-offs:\n" + "\n".join(revisions) + "\n")
        else:
            sections.append("Specialist proposals reached initial consensus in Round 1; no resource trade-offs or proposal revisions were required.\n")

        # 4. Minority Report & Open Amendment Notes
        last_round_num = max(bb.critiques.keys()) if bb.critiques else rounds_used
        final_critiques = bb.critiques.get(last_round_num, [])

        unresolved_conflicts = [
            c for c in final_critiques if not c.resolved and c.stance == CritiqueStance.CONFLICT
        ]
        unresolved_amends = [
            c for c in final_critiques if not c.resolved and c.stance == CritiqueStance.AMEND
        ]

        if unresolved_conflicts:
            sections.append("## Minority Report: Unresolved Conflicts\n")
            sections.append(
                "The panel did not reach consensus on the following items. "
                "Options are presented below for stakeholder review and value judgment:\n"
            )
            for idx, c in enumerate(unresolved_conflicts, 1):
                target_prop = proposals.get(c.target_agent_id)
                target_position = target_prop.summary if target_prop else "Specialist proposed action"
                target_recs = target_prop.recommendations if target_prop else []
                sections.append(f"### Conflict: {c.issue_type} ({c.target_agent_id} vs {c.reviewer_agent_id})")
                sections.append(f"### Option A ({c.target_agent_id} Position)")
                sections.append(f"- **Position**: {target_position}")
                if target_recs:
                    sections.append("- **Recommendations**:")
                    for r in target_recs:
                        sections.append(f"  - {r}")
                sections.append(f"### Option B ({c.reviewer_agent_id} Position)")
                sections.append(f"- **Objection**: {c.critique}")
                sections.append(f"- **Proposed Resolution**: {c.proposed_resolution}")
                sections.append("- **Stakeholder Decision Required**: Value judgment and review required by human stakeholder.\n")

        if unresolved_amends:
            sections.append("## Open Amendment Notes\n")
            sections.append("The following amendment suggestions remain open for human review:\n")
            for c in unresolved_amends:
                sections.append(
                    f"- **`{c.reviewer_agent_id}` -> `{c.target_agent_id}`** ({c.issue_type}): "
                    f"{c.critique} (Proposed: {c.proposed_resolution})"
                )
            sections.append("")

        if not unresolved_conflicts and not unresolved_amends:
            sections.append("## Deliberation Outcome\n")
            sections.append("All peer critiques and constraints were successfully resolved across deliberation rounds. Full consensus achieved.\n")

        # 5. Canonical Deduplicated Disclaimer Footer
        sections.append(CANONICAL_DISCLAIMER)

        full_output = "\n".join(sections)
        state["output"] = full_output
        return full_output

    @class_or_instance_method
    def synthesize_response(self, state: Dict[str, Any]) -> str:
        """Synthesizes specialist outputs and deliberation state into a coordinated plan."""
        # Check if deliberation state is present
        if state.get("deliberation_state"):
            return self.synthesize_deliberation(state)

        specialist_outputs = state.get("specialist_outputs")
        if specialist_outputs is None:
            specialist_outputs = {}

        # If no specialist_outputs, check if single output exists in state
        if not specialist_outputs:
            single_out = state.get("output")
            if not single_out:
                for m in reversed(state.get("messages", [])):
                    msg_type = getattr(m, "type", "")
                    if msg_type in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")):
                        break
                    if isinstance(m, AIMessage) and m.content:
                        single_out = m.content
                        break
                    elif isinstance(m, dict) and m.get("role") in ("assistant", "ai") and m.get("content"):
                        single_out = m.get("content")
                        break
            if single_out:
                clean_text = self.strip_disclaimers(str(single_out))
                full_output = f"{clean_text}\n\n{CANONICAL_DISCLAIMER}"
                state["output"] = full_output
                return full_output
            full_output = f"No specialist outputs were generated.\n\n{CANONICAL_DISCLAIMER}"
            state["output"] = full_output
            return full_output

        # Single agent fast-path
        if len(specialist_outputs) == 1:
            single_text = str(list(specialist_outputs.values())[0])
            clean_text = self.strip_disclaimers(single_text)
            full_output = f"{clean_text}\n\n{CANONICAL_DISCLAIMER}"
            state["output"] = full_output
            return full_output

        # Multi-agent synthesis (domain-neutral coordination summary)
        sections: List[str] = ["# Multi-Agent Coordination Summary\n"]
        for agent_id, output_text in specialist_outputs.items():
            agent_title = str(agent_id).replace("-", " ").replace("_", " ").title()
            clean_output = self.strip_disclaimers(str(output_text))
            sections.append(f"## {agent_title} Perspective\n{clean_output}\n")
        sections.append(CANONICAL_DISCLAIMER)

        full_output = "\n".join(sections)
        state["output"] = full_output
        return full_output

    async def execute(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """LangGraph node execution interface with Phase 5 turn persistence."""
        full_output = self.synthesize_response(state)

        # Zero-body structured audit event logging (event="synthesis")
        iso_timestamp = datetime.now(timezone.utc).isoformat()
        agent_id = str(state.get("current_agent") or "response-synthesizer")
        specialist_outputs = state.get("specialist_outputs") or {}
        specialist_ids = list(specialist_outputs.keys())
        thread_id = state.get("thread_id")

        audit_payload: Dict[str, Any] = {
            "timestamp": iso_timestamp,
            "ts": iso_timestamp,
            "agent_id": agent_id,
            "event": "synthesis",
            "allowed": True,
            "target_agents": specialist_ids,
        }
        if thread_id:
            audit_payload["thread_id"] = str(thread_id)
        if state.get("prompt"):
            audit_payload["prompt"] = str(state["prompt"])
        if state.get("output"):
            audit_payload["completion"] = str(state["output"])

        store_bodies = bool(state.get("store_bodies", settings.audit_store_bodies))
        redacted = redact_audit_event(audit_payload, store_bodies=store_bodies)
        redacted = {k: v for k, v in redacted.items() if v is not None}
        redacted["timestamp"] = iso_timestamp
        redacted["ts"] = iso_timestamp

        if settings.audit_log_path:
            log_path = Path(settings.audit_log_path)
        else:
            ws_root = state.get("workspace_root")
            if ws_root and not (Path(ws_root) / "backend").is_dir() and Path(ws_root).resolve() != settings.workspace_root:
                log_path = Path(ws_root) / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE
            else:
                log_path = settings.get_audit_log_path()

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(redacted) + "\n"
            with _file_lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
        except Exception as err:
            self.logger.warning("ResponseSynthesizerNode failed to write audit event: %s", err)

        accumulated = list(state.get("audit_events", []))
        accumulated.append(redacted)

        # Suggestion chips (domain-neutral)
        follow_ups = list(state.get("follow_up_suggestions") or [])
        if not follow_ups:
            if state.get("deliberation_state"):
                follow_ups = [
                    "Review coordinated deliberation plan with team",
                    "Evaluate resource allocation constraints",
                    "Review open minority report options and amendment notes",
                ]
            elif len(state.get("specialist_outputs", {})) > 1:
                follow_ups = [
                    "Review multi-agent summary with stakeholders",
                    "Prioritize next operational steps",
                    "Verify resource allocations against budget",
                ]

        # Phase 5 Turn Persistence: Commit interaction into episodic memory
        if store is not None and thread_id:
            try:
                turn_key = f"turn_{int(time.time() * 1000)}"
                user_prompt = state.get("prompt") or self.get_prompt_text(state) or ""
                turn_payload = {
                    "role": "assistant",
                    "user_query": user_prompt,
                    "user_prompt": user_prompt,
                    "prompt": user_prompt,
                    "agent_response": full_output,
                    "response": full_output,
                    "output": full_output,
                    "agent_id": agent_id,
                    "tier": "EPISODIC",
                    "timestamp": iso_timestamp,
                    "text": f"User: {user_prompt}\nYarvelle Core: {full_output}",
                    "metadata": {
                        "thread_id": str(thread_id),
                        "agent_id": agent_id,
                        "turn_key": turn_key,
                        "specialist_outputs": specialist_ids,
                    },
                    "created_at": iso_timestamp,
                    "updated_at": iso_timestamp,
                }
                await store.aput(
                    ("memories", str(thread_id)),
                    turn_key,
                    turn_payload,
                )
            except Exception as err:
                self.logger.warning("Phase 5 turn persistence failed gracefully: %s", err)

        # SSE custom event dispatching
        if specialist_outputs or state.get("deliberation_state"):
            try:
                await adispatch_custom_event(
                    "synthesis",
                    {
                        "type": "synthesis",
                        "output": full_output,
                    },
                )
            except Exception:
                pass

        clean_completion = self.strip_disclaimers(full_output)
        result_payload: Dict[str, Any] = {
            "output": clean_completion if not (specialist_outputs or state.get("deliberation_state")) else full_output,
            "next_step": "output_guardrail",
            "audit_events": accumulated,
        }
        if specialist_outputs or state.get("deliberation_state") or not any(isinstance(m, AIMessage) for m in state.get("messages", [])):
            result_payload["messages"] = [AIMessage(content=full_output)]
        if follow_ups:
            result_payload["follow_up_suggestions"] = follow_ups

        return result_payload

    # Method alias for process requirement compatibility
    process = execute


__all__ = ["ResponseSynthesizerNode", "CANONICAL_DISCLAIMER"]
