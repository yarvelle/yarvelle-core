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

"""Critic and self-correction loop node (F-28).

Increments reflection counter, generates self-correction feedback prompts,
preserves previous output attempts, and enforces strict max_reflections retry ceilings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage
from yarvelle_core.constants.defaults import DEFAULT_MAX_REFLECTIONS
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID
from yarvelle_core.workflows.nodes.base import BaseNode


def _is_human_message(msg: Any) -> bool:
    return getattr(msg, "type", "") in ("human", "user") or (
        isinstance(msg, dict) and msg.get("role") in ("human", "user")
    )


def _find_current_turn_non_tool_ai_removals(messages: Any) -> List[RemoveMessage]:
    """Builds RemoveMessage directives for rejected non-tool AI drafts in the latest turn."""
    if not isinstance(messages, (list, tuple)) or not messages:
        return []
    last_human_idx = -1
    for idx, msg in enumerate(messages):
        if _is_human_message(msg):
            last_human_idx = idx
    if last_human_idx < 0:
        return []
    removals: List[RemoveMessage] = []
    for msg in messages[last_human_idx + 1 :]:
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            msg_id = getattr(msg, "id", None)
            if msg_id:
                removals.append(RemoveMessage(id=str(msg_id)))
    return removals


def strip_current_turn_assistant_drafts(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """Removes rejected non-tool assistant drafts after the latest human message."""
    items = list(messages or [])
    last_human_idx = -1
    for idx, msg in enumerate(items):
        if getattr(msg, "type", "") in ("human", "user"):
            last_human_idx = idx
    if last_human_idx < 0:
        return items
    cleaned = items[: last_human_idx + 1]
    for msg in items[last_human_idx + 1 :]:
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            continue
        cleaned.append(msg)
    return cleaned


def build_reflection_directive(state: Dict[str, Any]) -> str:
    """Formats a self-correction directive for system prompts during reflection retries."""
    reflection_count = int(state.get("reflection_count", 0) or 0)
    if reflection_count <= 0:
        return ""
    critique = str(state.get("critique") or "").strip()
    parts = [
        "# SELF-CORRECTION DIRECTIVE",
        critique
        or (
            "The previous draft violated safety guardrails. "
            "Rewrite your answer from scratch in your assistant role to provide general navigation "
            "and informational support only."
        ),
        "IMPORTANT: Reply directly to the user's latest message in your assistant role (never reply as the user).",
    ]
    prev = state.get("previous_attempts") or []
    if isinstance(prev, (list, tuple)) and prev:
        last_draft = str(prev[-1] or "").strip()
        if last_draft:
            excerpt = last_draft[:500] + ("..." if len(last_draft) > 500 else "")
            parts.append(f"Rejected previous draft (do not repeat verbatim):\n{excerpt}")
    return "\n".join(parts)


def append_ephemeral_reflection_reminder(
    messages: Sequence[BaseMessage],
    state: Dict[str, Any],
) -> List[BaseMessage]:
    """Appends an ephemeral revision note to a copy of the trailing human turn during reflection retries."""
    items = list(messages or [])
    if int(state.get("reflection_count", 0) or 0) <= 0 or not items:
        return items
    last = items[-1]
    if isinstance(last, HumanMessage):
        reason = str(state.get("refusal_reason") or "safety boundary")
        note = (
            f"[SELF-CORRECTION NOTE — DO NOT ECHO THIS NOTE: "
            f"Your previous draft tripped a safety boundary ({reason}). "
            f"Rewrite your reply in your assistant role WITHOUT writing the words \"you have\" or \"that you have\" anywhere "
            f"(write \"you mentioned managing ...\" or \"your experience with ...\" instead), "
            f"and provide general informational navigation only.]"
        )
        orig = str(getattr(last, "content", "") or "")
        combined = f"{orig}\n\n{note}" if orig else note
        items[-1] = HumanMessage(content=combined, id=getattr(last, "id", None))
    return items


class ReflectionNode(BaseNode):
    """Critic and self-correction loop capped by max retries."""

    def __init__(
        self,
        max_reflections: int = DEFAULT_MAX_REFLECTIONS,
        name: str = "reflection",
    ) -> None:
        super().__init__(name=name)
        self.max_reflections = max_reflections

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates retry budget and increments reflection count."""
        raw_count = state.get("reflection_count", 0)
        current_count = max(0, int(raw_count))
        max_refl = int(state.get("max_reflections", self.max_reflections))

        # A refused main-agent answer ends on the refusal path. The retry edge
        # goes to the single-agent node, which cannot run the main agent, and
        # rerunning the main agent would repeat every hand-off.
        if state.get("current_agent") == MAIN_AGENT_ID:
            return {
                "reflection_count": current_count,
                "next_step": "refusal",
                "critique": "The coordinated answer was refused; returning the refusal.",
                "previous_attempts": list(state.get("previous_attempts", [])),
            }

        # Ceiling check: if max_reflections is 0 or current count reached ceiling
        if max_refl <= 0 or current_count >= max_refl:
            return {
                "reflection_count": current_count,
                "next_step": "done",
                "critique": "Maximum reflection retries reached. Halting self-correction loop.",
                "previous_attempts": list(state.get("previous_attempts", [])),
            }

        new_count = current_count + 1
        previous_attempts = list(state.get("previous_attempts", []))
        if state.get("output"):
            previous_attempts.append(str(state["output"]))

        critique = (
            f"Self-correction directive (Attempt {new_count} of {max_refl}): "
            f"The previous response violated safety guardrails ({state.get('refusal_reason', 'prohibited intent')}). "
            f"Rewrite your answer from scratch in your assistant role to provide general navigation and informational support only. "
            f"Never write 'you have' or 'that you have' (use 'you mentioned managing ...' or 'your experience with ...' instead). "
            f"Attribute any user-shared condition, reading, or fact to the user rather than asserting it directly. "
            f"Do not provide unauthorized determinations, dosage calculations, or authoritative advice."
        )

        next_step = "agent"
        result: Dict[str, Any] = {
            "reflection_count": new_count,
            "next_step": next_step,
            "critique": critique,
            "previous_attempts": previous_attempts,
        }
        remove_msgs = _find_current_turn_non_tool_ai_removals(state.get("messages"))
        if remove_msgs:
            result["messages"] = remove_msgs

        return result


__all__ = [
    "ReflectionNode",
    "append_ephemeral_reflection_reminder",
    "build_reflection_directive",
    "strip_current_turn_assistant_drafts",
]
