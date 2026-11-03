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

"""Unit tests for the in-process A2A-style hand-off shapes."""

from __future__ import annotations

from datetime import datetime
import json
import pytest
from pydantic import TypeAdapter, ValidationError

from yarvelle_core.schemas.a2a import (
    A2A_PROTOCOL_VERSION,
    A2AArtifact,
    A2AMessage,
    A2ATask,
    A2ATaskState,
    A2ATaskStatus,
    DataPart,
    FilePart,
    Part,
    TERMINAL_TASK_STATES,
    TextPart,
)

DIGEST = "a" * 64


def _task(**overrides: object) -> A2ATask:
    data: dict = {
        "id": "task-1",
        "context_id": "thread-1",
        "status": {"state": "working"},
    }
    data.update(overrides)
    return A2ATask.model_validate(data)


def test_protocol_version_is_pinned() -> None:
    assert A2A_PROTOCOL_VERSION == "0.3.0"


def test_task_states_match_protocol_values() -> None:
    assert {s.value for s in A2ATaskState} == {
        "submitted",
        "working",
        "input-required",
        "completed",
        "canceled",
        "failed",
        "rejected",
    }
    assert A2ATaskState.WORKING not in TERMINAL_TASK_STATES
    assert A2ATaskState.COMPLETED in TERMINAL_TASK_STATES


def test_part_discriminator_selects_concrete_type() -> None:
    adapter = TypeAdapter(Part)
    assert isinstance(adapter.validate_python({"kind": "text", "text": "hi"}), TextPart)
    assert isinstance(adapter.validate_python({"kind": "data", "data": {"k": 1}}), DataPart)
    file_part = adapter.validate_python({"kind": "file", "file": {"casRef": DIGEST, "mimeType": "text/plain"}})
    assert isinstance(file_part, FilePart)
    assert file_part.file.mime_type == "text/plain"
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "audio", "text": "x"})


def test_file_part_requires_cas_reference_not_inline_bytes() -> None:
    with pytest.raises(ValidationError):
        FilePart.model_validate({"file": {"cas_ref": "not-a-digest"}})
    with pytest.raises(ValidationError):
        FilePart.model_validate({"file": {"cas_ref": DIGEST, "bytes": "AAAA"}})


def test_message_requires_parts_and_known_role() -> None:
    with pytest.raises(ValidationError):
        A2AMessage(role="agent", parts=[])
    with pytest.raises(ValidationError):
        A2AMessage.model_validate({"role": "system", "parts": [{"kind": "text", "text": "x"}]})


def test_task_round_trips_through_camel_case_json() -> None:
    msg = A2AMessage(role="user", parts=[TextPart(text="hello")], task_id="task-1", context_id="thread-1")
    art = A2AArtifact(name="answer", parts=[TextPart(text="done")])
    task = _task(history=[msg.model_dump()], artifacts=[art.model_dump()])

    wire = task.model_dump(mode="json", by_alias=True)
    assert wire["contextId"] == "thread-1"
    assert wire["history"][0]["messageId"] == msg.message_id
    assert wire["artifacts"][0]["artifactId"] == art.artifact_id
    assert wire["kind"] == "task"

    restored = A2ATask.model_validate(json.loads(json.dumps(wire)))
    assert restored == task


def test_task_rejects_history_from_another_task() -> None:
    foreign = A2AMessage(role="user", parts=[TextPart(text="x")], task_id="task-2")
    with pytest.raises(ValidationError, match="belongs to task"):
        _task(history=[foreign.model_dump()])


def test_task_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _task(transport="http")


def test_status_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        A2ATaskStatus(state=A2ATaskState.WORKING, timestamp=datetime(2026, 1, 1))


def test_is_terminal() -> None:
    assert _task(status={"state": "completed"}).is_terminal
    assert not _task(status={"state": "input-required"}).is_terminal
