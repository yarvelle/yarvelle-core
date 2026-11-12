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

"""Thin async execution handlers for Yarvelle Core declarative built-in tools.

Tool metadata, JSON Schemas, risk tiers, and egress allowlists live exclusively in
``yarvelle_core/resources/tools/*.yaml`` (Spector ADR-0025 pattern). Every handler
in this module is registered via ``@builtin_tool_handler`` and verified for 1:1
parity against the declarative catalog by ``tests/test_tool_spec_schema_validation.py``.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Coroutine, Dict, Mapping, Optional

BuiltinHandlerFn = Callable[[Dict[str, Any], Any], Coroutine[Any, Any, Any]]

BUILTIN_TOOL_HANDLERS: Dict[str, BuiltinHandlerFn] = {}


def builtin_tool_handler(tool_name: str) -> Callable[[BuiltinHandlerFn], BuiltinHandlerFn]:
    """Registers an async Python callable as the canonical handler for ``tool_name``."""

    def _decorator(fn: BuiltinHandlerFn) -> BuiltinHandlerFn:
        if tool_name in BUILTIN_TOOL_HANDLERS:
            raise ValueError(f"Duplicate built-in tool handler registration for '{tool_name}'.")
        BUILTIN_TOOL_HANDLERS[tool_name] = fn
        return fn

    return _decorator


@builtin_tool_handler("attach-read")
async def exec_attach_read(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.attach_read import execute_attach_read

    return await execute_attach_read(args or {}, ctx)


@builtin_tool_handler("workspace-note")
async def exec_workspace_note(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.workspace_note import execute_workspace_note

    return await execute_workspace_note(args or {}, ctx)


@builtin_tool_handler("skill-docs")
async def exec_skill_docs(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.skill_docs import execute_skill_docs

    return await execute_skill_docs(args or {}, ctx)


@builtin_tool_handler("delegate_to_agent")
async def exec_delegate_to_agent(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.delegation_tools import DelegateToAgentTool

    payload = args or {}
    tool = DelegateToAgentTool()
    agent_id = str(payload.get("agent_id", "")).strip()
    instructions = str(payload.get("instructions", "")).strip()
    return await tool._arun(agent_id=agent_id, instructions=instructions)


@builtin_tool_handler("list_agents")
async def exec_list_agents(args: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Any:
    from yarvelle_core.tools.delegation_tools import ListAgentsTool

    payload = args or {}
    tool = ListAgentsTool()
    return await tool._arun(query=str(payload.get("query") or ""), limit=payload.get("limit"))


@builtin_tool_handler("sanitize_pii")
async def exec_sanitize_pii(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.extraction_tools import SanitizePIITool

    payload = args or {}
    tool = SanitizePIITool()
    text = str(payload.get("text", ""))
    mask_type = str(payload.get("mask_type", "tag"))
    return await tool._arun(text=text, mask_type=mask_type)


@builtin_tool_handler("extract_structured_data")
async def exec_extract_structured_data(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.extraction_tools import ExtractStructuredDataTool

    payload = args or {}
    tool = ExtractStructuredDataTool()
    text = str(payload.get("text", ""))
    schema_type = str(payload.get("schema_type", "generic"))
    return await tool._arun(text=text, schema_type=schema_type)


@builtin_tool_handler("validate_grounding")
async def exec_validate_grounding(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.extraction_tools import ValidateGroundingTool

    payload = args or {}
    tool = ValidateGroundingTool()
    dossier = payload.get("dossier", {})
    source_text = str(payload.get("source_text", ""))
    return await tool._arun(dossier=dossier, source_text=source_text)


@builtin_tool_handler("extract_document_dossier")
async def exec_extract_document_dossier(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.workflows.subgraphs.extraction.tool import extract_document_dossier

    return await extract_document_dossier._arun(**(args or {}))


@builtin_tool_handler("search_records")
async def exec_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.search_records import execute_search_records

    return await execute_search_records(args or {}, ctx)


@builtin_tool_handler("create_reminder")
async def exec_create_reminder(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.reminders import execute_create_reminder

    return await execute_create_reminder(args or {}, ctx)


@builtin_tool_handler("list_reminders")
async def exec_list_reminders(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.reminders import execute_list_reminders

    return await execute_list_reminders(args or {}, ctx)


@builtin_tool_handler("web_search")
async def exec_web_search(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.tools.web_search import execute_web_search

    return await execute_web_search(args or {}, ctx)


def _build_connector_ctx(ctx: Any, connector_id: str) -> Any:
    from yarvelle_core.connectors.base import ToolContext as ConnectorToolContext

    if isinstance(ctx, ConnectorToolContext):
        return ctx
    return ConnectorToolContext(
        user_id=str(getattr(ctx, "user_id", "") or ""),
        profile_id=str(getattr(ctx, "profile_id", "") or ""),
        run_id=str(getattr(ctx, "run_id", "") or connector_id),
    )


@builtin_tool_handler("calendar_suggest_slots")
async def exec_calendar_suggest_slots(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.connectors.starters.calendar import GoogleCalendarConnector

    connector = GoogleCalendarConnector()
    conn_ctx = _build_connector_ctx(ctx, "google-calendar")
    for tool_spec in connector.tools():
        if tool_spec.name == "calendar_suggest_slots" and tool_spec.handler is not None:
            return await tool_spec.handler(conn_ctx, args or {})
    return {"slots": []}


@builtin_tool_handler("calendar_create_event")
async def exec_calendar_create_event(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.connectors.starters.calendar import GoogleCalendarConnector

    payload = dict(args or {})
    if "start" not in payload and "start_time" in payload:
        payload["start"] = payload["start_time"]
    if "end" not in payload and "end_time" in payload:
        payload["end"] = payload["end_time"]
    if "strip_sensitive" not in payload and "redact_title" in payload:
        payload["strip_sensitive"] = bool(payload["redact_title"])

    connector = GoogleCalendarConnector()
    conn_ctx = _build_connector_ctx(ctx, "google-calendar")
    for tool_spec in connector.tools():
        if tool_spec.name == "calendar_create_event" and tool_spec.handler is not None:
            return await tool_spec.handler(conn_ctx, payload)
    return {"status": "created"}


@builtin_tool_handler("create_email_draft")
async def exec_create_email_draft(args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.platform.email_drafts import execute_create_email_draft

    payload = dict(args or {})
    if "body" not in payload and "body_markdown" in payload:
        payload["body"] = payload["body_markdown"]
    if "recipient" not in payload and "recipient_email" in payload:
        payload["recipient"] = payload["recipient_email"]
    return await execute_create_email_draft(payload, ctx)


async def _invoke_gmail_mcp(tool_name: str, args: Dict[str, Any], ctx: Any = None) -> Any:
    from yarvelle_core.connectors.errors import ConnectorNotConfiguredError
    from yarvelle_core.engine.tool_exec import TaintFlag, UntrustedResult

    if ctx is None or not getattr(ctx, "profile_id", None):
        raise ValueError("Missing profile_id in ToolContext")

    extra = getattr(ctx, "extra", None)
    mcp_client = getattr(ctx, "mcp_client", None) or (
        extra.get("mcp_client") if isinstance(extra, Mapping) else None
    )
    if mcp_client is None:
        raise ConnectorNotConfiguredError(
            f"Remote MCP connector 'google-workspace-gmail' is not configured or attached for tool '{tool_name}'."
        )

    call_fn = getattr(mcp_client, "call_tool", None)
    if callable(call_fn):
        raw = call_fn(tool_name, dict(args or {}))
    elif callable(mcp_client):
        raw = mcp_client(tool_name, dict(args or {}))
    else:
        raise ConnectorNotConfiguredError(
            f"Attached MCP client for 'google-workspace-gmail' does not implement 'call_tool' for '{tool_name}'."
        )

    if inspect.isawaitable(raw):
        raw = await raw

    taint_attr = getattr(ctx, "taint", None)
    if taint_attr is not None and hasattr(taint_attr, "set"):
        taint_attr.set()
    else:
        try:
            setattr(ctx, "taint", TaintFlag(True))
        except Exception:
            pass

    if isinstance(raw, UntrustedResult):
        return raw
    return UntrustedResult(
        data=raw,
        taint=True,
        source=f"mcp:google-workspace-gmail:{tool_name}",
    )


@builtin_tool_handler("gmail_list_messages")
async def exec_gmail_list_messages(args: Dict[str, Any], ctx: Any = None) -> Any:
    return await _invoke_gmail_mcp("gmail_list_messages", args or {}, ctx)


@builtin_tool_handler("gmail_send_message")
async def exec_gmail_send_message(args: Dict[str, Any], ctx: Any = None) -> Any:
    return await _invoke_gmail_mcp("gmail_send_message", args or {}, ctx)


__all__ = [
    "BUILTIN_TOOL_HANDLERS",
    "BuiltinHandlerFn",
    "builtin_tool_handler",
    "exec_attach_read",
    "exec_calendar_create_event",
    "exec_calendar_suggest_slots",
    "exec_create_email_draft",
    "exec_create_reminder",
    "exec_delegate_to_agent",
    "exec_extract_document_dossier",
    "exec_extract_structured_data",
    "exec_gmail_list_messages",
    "exec_gmail_send_message",
    "exec_list_agents",
    "exec_list_reminders",
    "exec_sanitize_pii",
    "exec_search_records",
    "exec_skill_docs",
    "exec_validate_grounding",
    "exec_web_search",
    "exec_workspace_note",
]
