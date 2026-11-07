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

"""Per-turn reminder for the main agent (``orchestration.delegation.reminder``).

Delegation rules in the system prompt sit above the whole conversation. On a
follow-up turn some models answer from the earlier reply instead of handing
the new question to a specialist. A short reminder next to the latest user
message fixes that.

The reminder goes into a copy of the latest user message, not a new system
message, because some providers accept system text only at the start. It is
model input only: the main agent's run starts from the copy, and the router
keeps only the messages the run adds, so the checkpoint and history keep the
user's own words.

A pack sets the text in ``pack.yaml``, or passes a Python hook
(:data:`MainAgentReminder`) to ``GraphBuilder(main_agent_reminder=...)``,
``AgentExecutionService(main_agent_reminder=...)`` or ``HybridRouter(reminder=...)``.
A hook replaces the ``pack.yaml`` text.
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from yarvelle_core.schemas.orchestration import DelegationReminderSpec

MainAgentReminder = Callable[[Sequence[BaseMessage], Mapping[str, Any]], Optional[str]]
"""Returns the reminder for this turn, or None/"" for none.

Called with the turn's messages (the latest is the user's) and the graph state.
"""


def ends_with_user(messages: Sequence[BaseMessage]) -> bool:
    """True when the latest message is the user's."""
    return bool(messages) and isinstance(messages[-1], HumanMessage)


def is_follow_up(messages: Sequence[BaseMessage]) -> bool:
    """True when the user spoke last and an earlier reply exists in the conversation."""
    return ends_with_user(messages) and any(isinstance(m, AIMessage) for m in messages[:-1])


def add_reminder(messages: Sequence[BaseMessage], text: str) -> List[BaseMessage]:
    """A copy of ``messages`` whose latest user message ends with ``text``.

    The original messages are not changed. Multipart content gets an extra
    text block. Messages that do not end with a user message are returned as is.
    """
    out = list(messages)
    if not text or not ends_with_user(out):
        return out
    last = out[-1]
    content = last.content
    if isinstance(content, str):
        new_content: Any = f"{content}\n\n{text}"
    else:
        new_content = [*list(content), {"type": "text", "text": text}]
    out[-1] = last.model_copy(update={"content": new_content})
    return out


def reminder_from_spec(spec: Optional[DelegationReminderSpec]) -> Optional[MainAgentReminder]:
    """The hook for a ``pack.yaml`` reminder, or None when it is not set."""
    if spec is None or not spec.text.strip():
        return None
    text = spec.text.strip()
    when = spec.when

    def _reminder(messages: Sequence[BaseMessage], state: Mapping[str, Any]) -> Optional[str]:
        if when == "always":
            return text if ends_with_user(messages) else None
        return text if is_follow_up(messages) else None

    return _reminder


def main_agent_messages(
    messages: Sequence[BaseMessage],
    state: Mapping[str, Any],
    reminder: Optional[MainAgentReminder],
) -> List[BaseMessage]:
    """The messages the main agent reads this turn (same length as ``messages``)."""
    out = list(messages)
    if reminder is None or not ends_with_user(out):
        return out
    text = reminder(out, state)
    if not text or not str(text).strip():
        return out
    return add_reminder(out, str(text).strip())


__all__ = [
    "MainAgentReminder",
    "add_reminder",
    "ends_with_user",
    "is_follow_up",
    "main_agent_messages",
    "reminder_from_spec",
]
