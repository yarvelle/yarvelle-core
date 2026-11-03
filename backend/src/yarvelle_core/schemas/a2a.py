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

"""In-process agent hand-off shapes modeled on the A2A protocol.

These pydantic models mirror the data objects of the Agent2Agent (A2A)
protocol (Task, TaskStatus, Message, Part, Artifact) so that every hand-off
between agents inside one turn uses a single typed, hashable envelope.

Only the data shapes are mirrored. There is no network transport, JSON-RPC
binding, or agent-card endpoint; all hand-offs stay inside the local process.

Deviations from the wire protocol are deliberate:

- Field names are snake_case in Python and serialize to the protocol's
  camelCase names with ``model_dump(by_alias=True)``.
- ``FilePart`` carries a content-addressed storage reference (``cas_ref``)
  instead of inline bytes or a URI, so file content never leaves the
  scoped store through a hand-off.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

A2A_PROTOCOL_VERSION = "0.3.0"
"""A2A specification version whose data shapes these models mirror."""

CAS_REF_PATTERN = r"^[0-9a-f]{64}$"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class _A2AModel(BaseModel):
    """Base model: forbids unknown fields and accepts camelCase or snake_case input."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )


class A2ATaskState(str, Enum):
    """Lifecycle states of an A2A task."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"


TERMINAL_TASK_STATES = frozenset(
    {
        A2ATaskState.COMPLETED,
        A2ATaskState.CANCELED,
        A2ATaskState.FAILED,
        A2ATaskState.REJECTED,
    }
)


class TextPart(_A2AModel):
    """Plain-text or markdown content."""

    kind: Literal["text"] = "text"
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FileRef(_A2AModel):
    """Reference to a file held in content-addressed storage."""

    cas_ref: str = Field(..., pattern=CAS_REF_PATTERN, description="SHA-256 hex digest of the stored blob.")
    name: Optional[str] = Field(default=None, description="Display file name.")
    mime_type: Optional[str] = Field(default=None, description="IANA media type of the file.")


class FilePart(_A2AModel):
    """File content passed by reference, never inline."""

    kind: Literal["file"] = "file"
    file: FileRef
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DataPart(_A2AModel):
    """Structured JSON content."""

    kind: Literal["data"] = "data"
    data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


Part = Annotated[Union[TextPart, FilePart, DataPart], Field(discriminator="kind")]
"""A single content part; the ``kind`` field selects the concrete type."""


class A2AMessage(_A2AModel):
    """One message exchanged between the caller and an agent."""

    kind: Literal["message"] = "message"
    message_id: str = Field(default_factory=_new_id)
    role: Literal["user", "agent"]
    parts: List[Part] = Field(..., min_length=1)
    task_id: Optional[str] = None
    context_id: Optional[str] = None
    reference_task_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class A2AArtifact(_A2AModel):
    """An output produced by an agent while working on a task."""

    artifact_id: str = Field(default_factory=_new_id)
    name: Optional[str] = None
    description: Optional[str] = None
    parts: List[Part] = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class A2ATaskStatus(_A2AModel):
    """Current state of a task, with an optional status message."""

    state: A2ATaskState
    message: Optional[A2AMessage] = None
    timestamp: datetime = Field(default_factory=_utc_now)

    @field_validator("timestamp")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class A2ATask(_A2AModel):
    """A unit of work handed to one agent, with its history and outputs."""

    kind: Literal["task"] = "task"
    id: str = Field(default_factory=_new_id)
    context_id: str = Field(..., min_length=1, description="Conversation context; the thread id in core.")
    status: A2ATaskStatus
    history: List[A2AMessage] = Field(default_factory=list)
    artifacts: List[A2AArtifact] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _history_belongs_to_task(self) -> A2ATask:
        for msg in self.history:
            if msg.task_id is not None and msg.task_id != self.id:
                raise ValueError(
                    f"history message {msg.message_id} belongs to task {msg.task_id}, not {self.id}"
                )
        return self

    @property
    def is_terminal(self) -> bool:
        """True when the task can no longer change state."""
        return self.status.state in TERMINAL_TASK_STATES


__all__ = [
    "A2A_PROTOCOL_VERSION",
    "A2AArtifact",
    "A2AMessage",
    "A2ATask",
    "A2ATaskState",
    "A2ATaskStatus",
    "DataPart",
    "FilePart",
    "FileRef",
    "Part",
    "TERMINAL_TASK_STATES",
    "TextPart",
]
