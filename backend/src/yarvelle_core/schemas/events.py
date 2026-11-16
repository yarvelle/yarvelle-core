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

"""Domain-neutral event payload schemas and builders for SSE emission."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from yarvelle_core.constants.api import SSE_EVENT_ENTITY_CHANGED
from yarvelle_core.scope.context import DEFAULT_SCOPE


class EntityChangedPayload(BaseModel):
    """Payload schema for live entity_changed SSE event emission."""

    type: str = Field(default=SSE_EVENT_ENTITY_CHANGED, description="Event type constant.")
    entity_type: str = Field(..., description="Canonical entity type name.")
    entity: str = Field(..., description="Alias for entity_type.")
    entity_id: str = Field(..., description="Unique entity or record identifier or slug.")
    record_id: str = Field(..., description="Alias for entity_id.")
    action: str = Field(..., description="Mutation action: created, updated, or deleted.")
    profile_id: str = Field(..., description="Profile identifier.")
    scope: str = Field(..., description="Scope identifier.")
    tool: str = Field(..., description="Name of the tool that produced the mutation.")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of the mutation.")


def _derive_action(tool_name: str, args: Dict[str, Any] | None, output: Any) -> str:
    """Infers the mutation action (created, updated, deleted) from output, args, or tool name."""
    if isinstance(output, dict) and output.get("action"):
        act = str(output["action"]).strip().lower()
        if act in ("created", "updated", "deleted"):
            return act
        if act in ("create", "insert", "add"):
            return "created"
        if act in ("update", "modify", "edit", "patch", "upsert"):
            return "updated"
        if act in ("delete", "remove"):
            return "deleted"

    if isinstance(args, dict) and args.get("action"):
        act = str(args["action"]).strip().lower()
        if act in ("create", "insert", "add", "created"):
            return "created"
        if act in ("update", "modify", "edit", "patch", "upsert", "updated"):
            return "updated"
        if act in ("delete", "remove", "deleted"):
            return "deleted"

    lowered = tool_name.lower()
    if any(p in lowered for p in ("create_", "insert_", "add_")) or any(
        lowered.endswith(s) for s in ("_create", "_created", "_insert", "_inserted", "_add", "_added")
    ):
        return "created"
    if any(p in lowered for p in ("delete_", "remove_")) or any(
        lowered.endswith(s) for s in ("_delete", "_deleted", "_remove", "_removed")
    ):
        return "deleted"
    return "updated"


def _derive_entity_type(tool_name: str, args: Dict[str, Any] | None, output: Any) -> str:
    """Infers the entity type name from output, args, or tool name."""
    if isinstance(output, dict):
        candidate = output.get("entity_type") or output.get("entity") or output.get("table")
        if candidate and isinstance(candidate, str):
            return candidate.strip()

    if isinstance(args, dict):
        candidate = args.get("entity_type") or args.get("entity") or args.get("table") or args.get("collection")
        if candidate and isinstance(candidate, str):
            return candidate.strip()

    cleaned = tool_name.lower().replace("-", "_")
    for prefix in (
        "create_",
        "update_",
        "delete_",
        "upsert_",
        "get_",
        "list_",
        "add_",
        "remove_",
        "record_",
        "mutate_",
        "db_record_",
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]

    for infix in ("_create_", "_update_", "_delete_", "_upsert_", "_get_", "_list_"):
        if infix in cleaned:
            cleaned = cleaned.split(infix, 1)[0]
            break

    for suffix in (
        "_record",
        "_records",
        "_item",
        "_items",
        "_create",
        "_update",
        "_delete",
        "_upsert",
        "_get",
        "_list",
        "_patch",
        "_snooze",
    ):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]

    if cleaned.startswith("profile_"):
        cleaned = cleaned[8:]

    return cleaned or "record"


def _derive_entity_id(args: Dict[str, Any] | None, output: Any) -> str:
    """Extracts the record or entity ID from output or args."""
    if isinstance(output, dict):
        for key in ("id", "entity_id", "record_id", "note_id", "reminder_id", "draft_id", "slug"):
            val = output.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()

        rec = output.get("record")
        if isinstance(rec, dict):
            for key in ("id", "slug", "entity_id", "record_id"):
                val = rec.get(key)
                if val is not None and str(val).strip():
                    return str(val).strip()

    if isinstance(args, dict):
        for key in ("id", "entity_id", "record_id", "slug", "note_id", "reminder_id", "draft_id"):
            val = args.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()

    return ""


def build_entity_changed_payload(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    output: Any = None,
    profile_id: Optional[str] = None,
    scope: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a validated dictionary payload for an entity_changed SSE event."""
    action = _derive_action(tool_name, args, output)
    entity_type = _derive_entity_type(tool_name, args, output)
    entity_id = _derive_entity_id(args, output)
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    prof = str(profile_id or (args.get("profile_id") if isinstance(args, dict) else None) or "default_profile").strip()
    sc = str(scope or (args.get("scope") if isinstance(args, dict) else None) or DEFAULT_SCOPE).strip()

    payload = EntityChangedPayload(
        type=SSE_EVENT_ENTITY_CHANGED,
        entity_type=entity_type,
        entity=entity_type,
        entity_id=entity_id,
        record_id=entity_id,
        action=action,
        profile_id=prof,
        scope=sc,
        tool=tool_name,
        timestamp=ts,
    )
    return payload.model_dump()
