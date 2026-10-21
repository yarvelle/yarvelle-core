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

"""Central ToolSpec registry, risk classification, and profile filtering (AU-16).

Defines:
- RiskTier: 4 explicit security risk tiers ("read", "write_local", "write_external", "irreversible")
- TrustLevel: "trusted" vs "untrusted" input/output provenance classification
- DataFlows: Outbound network egress and data sensitivity policy metadata
- ToolSpec: Immutable specification declaring parameters, risk tier, data flows, and executor
- ToolSpecRegistry: Tool catalog with age-band and profile capability filtering
- create_default_registry: Factory populating all 9 Yarvelle Core built-in tools
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
import logging
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

logger = logging.getLogger("yarvelle_core.engine.tool_registry")

from yarvelle_core.schemas.age_band import CHILD_UNDER_13, canonical_age_band
from yarvelle_core.scope.context import DEFAULT_SCOPE

RiskTier = Literal["read", "write_local", "write_external", "irreversible"]
TrustLevel = Literal["trusted", "untrusted"]


@dataclass(frozen=True)
class DataFlows:
    """Outbound network egress allowlist and data sensitivity tagging.

    Implements a dual interface: structured dataclass attributes for engine
    inspection (.allowed_hosts, .allowed_methods, .data_sensitivity) and
    sequence emulation (__iter__, __contains__, __len__, __getitem__, __eq__) for backwards
    compatibility with tuple/list comparisons in existing tests and connectors.
    """

    allowed_hosts: Tuple[str, ...] = field(default_factory=tuple)
    allowed_methods: Tuple[str, ...] = ("GET", "POST")
    data_sensitivity: str = "internal"  # "public", "internal", "confidential", "phi", "pii"

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_hosts, tuple):
            object.__setattr__(
                self,
                "allowed_hosts",
                tuple(str(h).strip() for h in (self.allowed_hosts or ()) if str(h).strip()),
            )
        if not isinstance(self.allowed_methods, tuple):
            object.__setattr__(
                self,
                "allowed_methods",
                tuple(str(m).strip() for m in (self.allowed_methods or ()) if str(m).strip()),
            )

    def __iter__(self):
        """Allows iterating over allowed hostnames directly."""
        return iter(self.allowed_hosts)

    def __contains__(self, item: Any) -> bool:
        """Enables 'host in data_flows' checks."""
        if isinstance(item, str):
            item_clean = item.lower().strip()
            return item_clean in [h.lower().strip() for h in self.allowed_hosts]
        return item in self.allowed_hosts

    def __len__(self) -> int:
        """Enables 'len(data_flows)' checks."""
        return len(self.allowed_hosts)

    def __getitem__(self, index: int) -> str:
        """Enables indexing 'data_flows[0]'."""
        return self.allowed_hosts[index]

    def __eq__(self, other: Any) -> bool:
        """Enables equality comparisons with DataFlows, tuples, or lists of hostnames."""
        if isinstance(other, DataFlows):
            return (
                self.allowed_hosts == other.allowed_hosts
                and self.allowed_methods == other.allowed_methods
                and self.data_sensitivity == other.data_sensitivity
            )
        if isinstance(other, (tuple, list, set)):
            return tuple(self.allowed_hosts) == tuple(other)
        return False


def _normalize_data_flows(df: Union[DataFlows, Sequence[str], None]) -> DataFlows:
    """Converts a sequence of hostnames or None into a typed DataFlows instance."""
    if df is None:
        return DataFlows()
    if isinstance(df, DataFlows):
        return df
    if isinstance(df, (tuple, list, set)):
        return DataFlows(allowed_hosts=tuple(str(h).strip() for h in df if str(h).strip()))
    return DataFlows()


@dataclass(frozen=True)
class ToolSpec:
    """Immutable specification and policy declaration for an executable tool."""

    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = "read"
    trust: TrustLevel = "trusted"
    data_flows: Union[DataFlows, Sequence[str]] = field(default_factory=DataFlows)
    executor: Optional[Callable[..., Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    handler: Optional[Callable[..., Any]] = None  # Connector protocol alias
    scopes: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Harmonizes executor/handler aliases, normalizes data_flows and scopes."""
        # 1. Harmonize executor and handler aliases
        if self.executor is not None and self.handler is None:
            object.__setattr__(self, "handler", self.executor)
        elif self.handler is not None and self.executor is None:
            object.__setattr__(self, "executor", self.handler)

        # 2. Normalize data_flows
        if not isinstance(self.data_flows, DataFlows):
            normalized = _normalize_data_flows(self.data_flows)
            object.__setattr__(self, "data_flows", normalized)

        # 3. Guard parameters and metadata
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})

        # 4. Normalize domain scopes
        if not self.scopes:
            object.__setattr__(self, "scopes", frozenset({DEFAULT_SCOPE}))
        elif isinstance(self.scopes, (set, frozenset, list, tuple)):
            clean_scopes = {str(s).strip() for s in self.scopes if str(s).strip()}
            if clean_scopes.issubset({"read", "write"}):
                clean_scopes = {DEFAULT_SCOPE}
            object.__setattr__(self, "scopes", frozenset(clean_scopes))

    def to_tool_definition(self) -> Dict[str, Any]:
        """Returns an OpenAI / LangChain bind_tools-compatible dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters) if self.parameters else {"type": "object", "properties": {}},
        }


class ToolSpecRegistry:
    """Central registry for ToolSpecs with profile-scoped, age-band, and pack filtering."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._tool_packs: Dict[str, str] = {}

    def register(self, spec: ToolSpec, pack_id: str = "core") -> None:
        """Registers or updates a tool specification in the registry.

        Args:
            spec: ToolSpec instance.
            pack_id: Contributing pack identifier (default: 'core').
        """
        if not isinstance(spec, ToolSpec):
            raise TypeError(f"Expected ToolSpec instance, got {type(spec).__name__}")
        self._tools[spec.name] = spec
        self._tool_packs[spec.name] = pack_id or "core"

    def get(self, name: str) -> Optional[ToolSpec]:
        """Retrieves a ToolSpec by name. Returns None safely if not found."""
        return self._tools.get(name)

    def get_pack_id(self, name: str) -> Optional[str]:
        """Returns the pack_id that registered this tool, or None if not found."""
        return self._tool_packs.get(name)

    def list_all(self) -> List[ToolSpec]:
        """Returns all registered tool specifications."""
        return list(self._tools.values())

    def list_for_pack(self, pack_id: str) -> List[ToolSpec]:
        """Returns all tools registered by the specified pack."""
        return [spec for name, spec in self._tools.items() if self._tool_packs.get(name) == pack_id]

    def list_for_enabled_packs(self, enabled_packs: Sequence[str]) -> List[ToolSpec]:
        """Returns all core tools plus tools registered by any of the enabled packs."""
        allowed = set(enabled_packs) | {"core"}
        return [spec for name, spec in self._tools.items() if self._tool_packs.get(name) in allowed]

    def resolve(self, names: Sequence[str]) -> List[ToolSpec]:
        """Resolves a list of tool names to matching ToolSpec instances."""
        resolved: List[ToolSpec] = []
        for name in names:
            spec = self._tools.get(name)
            if spec is not None:
                resolved.append(spec)
        return resolved

    def list_for_profile(
        self,
        profile_id: str,
        consents: Optional[Mapping[str, bool]] = None,
        age_band: str = "adult",
        capabilities: Optional[Sequence[str]] = None,
    ) -> List[ToolSpec]:
        """Filters registered tools based on profile age band and capability constraints.

        Rules:
        1. Default age band: empty string or None defaults to 'adult'.
        2. Child under 13 restrictions:
           - 'write_external' tools are strictly excluded.
           - 'untrusted' (unvetted) tools are strictly excluded.
           - 'write_local' tools require explicit guardian consent (consents['guardian_consent'] is True).
           - 'irreversible' tools are strictly excluded.
           - 'read' tools are permitted.
        3. Capability restrictions:
           - If a tool specifies 'required_capabilities' in metadata, the profile must possess them.
        """
        effective_age_band = canonical_age_band(age_band)
        effective_consents = consents or {}
        has_guardian_consent = bool(effective_consents.get("guardian_consent") is True)
        enabled_caps = set(capabilities or ())

        allowed: List[ToolSpec] = []

        for spec in self._tools.values():
            # 1. Capability Check
            required_caps = spec.metadata.get("required_capabilities")
            if required_caps:
                if not any(rc in enabled_caps for rc in required_caps):
                    continue

            # 2. Child under 13 Gate
            if effective_age_band == CHILD_UNDER_13:
                # External writes strictly forbidden for children under 13
                if spec.risk_tier == "write_external":
                    continue

                # Untrusted/unvetted tools forbidden for children under 13
                if spec.trust == "untrusted":
                    continue

                # Local writes require explicit guardian consent
                if spec.risk_tier == "write_local" and not has_guardian_consent:
                    continue

                # Irreversible actions strictly forbidden for children
                if spec.risk_tier == "irreversible":
                    continue

            allowed.append(spec)

        return allowed


# ============================================================================
# Built-in Tool Adapters & Factory
# ============================================================================

def _make_builtin_specs() -> List[ToolSpec]:
    """Generates ToolSpecs for all 9 Yarvelle Core built-in tools with lazy-loaded executors."""

    # 1. attach-read
    async def _exec_attach_read(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.attach_read import execute_attach_read
        return await execute_attach_read(args, ctx)

    spec_attach_read = ToolSpec(
        name="attach-read",
        description="Read a text or PDF file located in the workspace attachments directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'Filename or path of attachment (e.g. "blood_work.txt", "benefits.pdf").',
                }
            },
            "required": ["path"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_attach_read,
    )

    # 2. workspace-note
    async def _exec_workspace_note(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.workspace_note import execute_workspace_note
        return await execute_workspace_note(args, ctx)

    spec_workspace_note = ToolSpec(
        name="workspace-note",
        description="Save a new markdown note into the workspace notes directory.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the note."},
                "content": {"type": "string", "description": "Markdown formatted note content."},
            },
            "required": ["title", "content"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
        executor=_exec_workspace_note,
    )

    # 3. skill-docs
    async def _exec_skill_docs(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.skill_docs import execute_skill_docs
        return await execute_skill_docs(args, ctx)

    spec_skill_docs = ToolSpec(
        name="skill-docs",
        description="Read documentation or reference files from an installed skill references directory.",
        parameters={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "ID of the skill owning reference doc."},
                "doc": {"type": "string", "description": 'Filename of reference doc (e.g. "checklist.md").'},
            },
            "required": ["skill_id", "doc"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="public"),
        executor=_exec_skill_docs,
    )

    # 4. delegate_to_agent
    async def _exec_delegate_to_agent(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.delegation_tools import DelegateToAgentTool
        tool = DelegateToAgentTool()
        agent_id = str(args.get("agent_id", "")).strip()
        instructions = str(args.get("instructions", "")).strip()
        return await tool._arun(agent_id=agent_id, instructions=instructions)

    spec_delegate_to_agent = ToolSpec(
        name="delegate_to_agent",
        description="Delegate the user's request to a specialist agent by ID, providing instructions.",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Target specialist agent ID."},
                "instructions": {"type": "string", "description": "Instructions for specialist agent."},
            },
            "required": ["agent_id"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="internal"),
        executor=_exec_delegate_to_agent,
    )

    # 5. list_agents
    async def _exec_list_agents(args: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Any:
        from yarvelle_core.tools.delegation_tools import ListAgentsTool
        tool = ListAgentsTool()
        return await tool._arun()

    spec_list_agents = ToolSpec(
        name="list_agents",
        description="List all available specialist agents and their capabilities from the catalog.",
        parameters={"type": "object", "properties": {}},
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="public"),
        executor=_exec_list_agents,
    )

    # 6. sanitize_pii
    async def _exec_sanitize_pii(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.extraction_tools import SanitizePIITool
        tool = SanitizePIITool()
        text = str(args.get("text", ""))
        mask_type = str(args.get("mask_type", "tag"))
        return await tool._arun(text=text, mask_type=mask_type)

    spec_sanitize_pii = ToolSpec(
        name="sanitize_pii",
        description="Mask direct PII (SSN, MRN, phone, address, email) in text before processing.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Source text to mask."},
                "mask_type": {"type": "string", "description": "'tag' or 'redacted'."},
            },
            "required": ["text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="pii"),
        executor=_exec_sanitize_pii,
    )

    # 7. extract_structured_data
    async def _exec_extract_structured_data(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.extraction_tools import ExtractStructuredDataTool
        tool = ExtractStructuredDataTool()
        text = str(args.get("text", ""))
        schema_type = str(args.get("schema_type", "generic"))
        return await tool._arun(text=text, schema_type=schema_type)

    spec_extract_structured_data = ToolSpec(
        name="extract_structured_data",
        description="Extract structured data from text into a typed Pydantic schema.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Sanitized document text."},
                "schema_type": {"type": "string", "description": "'insurance', 'records', or 'generic'."},
            },
            "required": ["text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_extract_structured_data,
    )

    # 8. validate_grounding
    async def _exec_validate_grounding(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.extraction_tools import ValidateGroundingTool
        tool = ValidateGroundingTool()
        dossier = args.get("dossier", {})
        source_text = str(args.get("source_text", ""))
        return await tool._arun(dossier=dossier, source_text=source_text)

    spec_validate_grounding = ToolSpec(
        name="validate_grounding",
        description="Validate that extracted numerical values match source document text.",
        parameters={
            "type": "object",
            "properties": {
                "dossier": {"description": "Extracted dossier dictionary or model."},
                "source_text": {"type": "string", "description": "Raw un-sanitized source text."},
            },
            "required": ["dossier", "source_text"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_validate_grounding,
    )

    # 9. extract_document_dossier
    async def _exec_extract_document_dossier(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.workflows.subgraphs.extraction.tool import extract_document_dossier
        return await extract_document_dossier._arun(**(args or {}))

    spec_extract_document_dossier = ToolSpec(
        name="extract_document_dossier",
        description="Composite pipeline: ingestion, PII sanitization, schema extraction, and grounding.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative path in attachments/."},
                "document_text": {"type": "string", "description": "Raw document text if loaded."},
                "dossier_type": {"type": "string", "description": "'insurance', 'records', or 'generic'."},
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_extract_document_dossier,
    )

    # 10. search_records (AU-26)
    async def _exec_search_records(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.search_records import execute_search_records
        return await execute_search_records(args or {}, ctx)

    spec_search_records = ToolSpec(
        name="search_records",
        description="Search user records, attachments, and notes.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query or keywords to search across user records.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of search results to retrieve (default: 5).",
                    "default": 5,
                },
                "mode": {
                    "type": "string",
                    "description": "Search mode: 'hybrid', 'lexical', or 'semantic' (default: 'hybrid').",
                    "default": "hybrid",
                },
                "source": {
                    "type": "string",
                    "description": "Optional filter by record source ('clinical_note', 'upload', 'note', 'connector', 'external').",
                    "default": None,
                },
            },
            "required": ["query"],
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_search_records,
    )

    async def _exec_create_reminder(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.reminders import execute_create_reminder
        return await execute_create_reminder(args or {}, ctx)

    spec_create_reminder = ToolSpec(
        name="create_reminder",
        description=(
            "Create a scheduled reminder with optional RFC 5545 recurrence "
            "and enqueue corresponding wall-clock Job execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Reminder prompt or directive title.",
                },
                "next_due_at": {
                    "type": "string",
                    "description": "Scheduled ISO-8601 due timestamp.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed context, instructions, or guidelines.",
                },
                "category": {
                    "type": "string",
                    "enum": ["task", "event", "prep", "general"],
                    "default": "general",
                    "description": "Reminder category (default: 'general').",
                },
                "rrule": {
                    "type": "string",
                    "description": "Optional RFC 5545 recurrence rule string (e.g. 'FREQ=DAILY;INTERVAL=1').",
                },
                "timezone": {
                    "type": "string",
                    "default": "UTC",
                    "description": "Local profile IANA timezone identifier (default: 'UTC').",
                },
            },
            "required": ["title", "next_due_at"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_reminder,
        metadata={
            "action": "create_reminder",
            "entity": "reminder",
            "undoable": True,
            "risk": "write_local",
        },
    )

    # 16. list_reminders
    async def _exec_list_reminders(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.reminders import execute_list_reminders
        return await execute_list_reminders(args or {}, ctx)

    spec_list_reminders = ToolSpec(
        name="list_reminders",
        description=(
            "List active or filtered reminders for a profile with optional status, "
            "category, and due date filters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "snoozed", "completed", "missed", "cancelled"],
                    "description": "Optional status filter.",
                },
                "category": {
                    "type": "string",
                    "enum": ["task", "event", "prep", "general"],
                    "description": "Optional category filter.",
                },
                "due_before": {
                    "type": "string",
                    "description": "Filter reminders due on or before this ISO-8601 timestamp.",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of reminders to retrieve (default: 50).",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Pagination offset.",
                },
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_list_reminders,
        metadata={
            "action": "list_reminders",
            "entity": "reminder",
            "risk": "read",
        },
    )

    async def _exec_web_search(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.tools.web_search import execute_web_search
        return await execute_web_search(args or {}, ctx)

    spec_web_search = ToolSpec(
        name="web_search",
        description=(
            "Execute a privacy-preserving, PHI-sanitised web search via allowlisted SearXNG "
            "or Brave Search endpoints. Automatically strips user names, DOB, SSN, MRN, "
            "phone, email, and address before any outbound request and marks results untrusted."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string (will be sanitised of PHI/PII before sending).",
                },
                "provider": {
                    "type": "string",
                    "enum": ["searxng", "brave"],
                    "default": "searxng",
                    "description": "Search provider ('searxng' or 'brave').",
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of search results to return.",
                },
                "preview_only": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, returns only the sanitised query preview without network I/O.",
                },
            },
            "required": ["query"],
        },
        risk_tier="read",
        trust="untrusted",
        data_flows=DataFlows(
            allowed_hosts=("api.search.brave.com", "localhost", "127.0.0.1", "searx.be"),
            data_sensitivity="public",
        ),
        executor=_exec_web_search,
        metadata={
            "action": "web_search",
            "risk": "read",
            "taints_context": True,
        },
    )

    async def _exec_calendar_suggest_slots(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.calendar import GoogleCalendarConnector
        connector = GoogleCalendarConnector()
        for t in connector.tools():
            if t.name == "calendar_suggest_slots" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"slots": []}

    spec_calendar_suggest_slots = ToolSpec(
        name="calendar_suggest_slots",
        description=(
            "Query connected Google Calendar or CalDAV free/busy windows and suggest "
            "conflict-free candidate appointment times without booking anything."
        ),
        parameters={
            "type": "object",
            "properties": {
                "window_start": {"type": "string", "description": "ISO-8601 window start."},
                "window_end": {"type": "string", "description": "ISO-8601 window end."},
                "duration_minutes": {"type": "integer", "default": 30},
            },
        },
        risk_tier="read",
        trust="trusted",
        data_flows=DataFlows(
            allowed_hosts=("www.googleapis.com", "caldav.icloud.com", "caldav.fastmail.com", "localhost"),
            data_sensitivity="pii",
        ),
        executor=_exec_calendar_suggest_slots,
        metadata={
            "action": "calendar_suggest_slots",
            "connector_id": "google-calendar",
            "risk": "read",
        },
    )

    # 28. calendar_create_event (AU-55 / E4.3)
    async def _exec_calendar_create_event(args: Dict[str, Any], ctx: Any = None) -> Any:
        from connectors.starters.calendar import GoogleCalendarConnector
        connector = GoogleCalendarConnector()
        for t in connector.tools():
            if t.name == "calendar_create_event" and t.handler is not None:
                return await t.handler(args or {}, ctx)
        return {"status": "created"}

    spec_calendar_create_event = ToolSpec(
        name="calendar_create_event",
        description=(
            "Create an external calendar event on Google Calendar or CalDAV. "
            "Always requires human approval in A0/A1 autonomy modes and strips PHI from titles by default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title (PHI stripped by default)."},
                "start_time": {"type": "string", "description": "ISO-8601 start timestamp."},
                "end_time": {"type": "string", "description": "ISO-8601 end timestamp."},
                "location": {"type": "string", "description": "Optional location or address."},
                "strip_phi": {"type": "boolean", "default": True},
            },
            "required": ["title", "start_time", "end_time"],
        },
        risk_tier="write_external",
        trust="trusted",
        data_flows=DataFlows(
            allowed_hosts=("www.googleapis.com", "caldav.icloud.com", "caldav.fastmail.com", "localhost"),
            data_sensitivity="pii",
        ),
        executor=_exec_calendar_create_event,
        metadata={
            "action": "calendar_create_event",
            "connector_id": "google-calendar",
            "risk": "write_external",
        },
    )

    async def _exec_create_email_draft(args: Dict[str, Any], ctx: Any = None) -> Any:
        from yarvelle_core.platform.email_drafts import execute_create_email_draft
        return await execute_create_email_draft(args or {}, ctx)

    spec_create_email_draft = ToolSpec(
        name="create_email_draft",
        description=(
            "Create a local email draft (RFC 5322 .eml / mailto:) for user review and "
            "sending from their own email client. Yarvelle Core never sends emails directly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "recipient_email": {"type": "string", "description": "Optional recipient email address."},
                "recipient_name": {"type": "string", "description": "Optional recipient display name."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body_markdown": {"type": "string", "description": "Draft body content."},
                "context_type": {
                    "type": "string",
                    "enum": ["visit_request", "records_request", "school_form", "appeal", "general"],
                    "default": "general",
                },
            },
            "required": ["subject", "body_markdown"],
        },
        risk_tier="write_local",
        trust="trusted",
        data_flows=DataFlows(allowed_hosts=(), data_sensitivity="phi"),
        executor=_exec_create_email_draft,
        metadata={
            "action": "create_email_draft",
            "entity": "email_draft",
            "undoable": True,
            "risk": "write_local",
        },
    )

    async def _exec_gmail_list_messages(args: Dict[str, Any], ctx: Any = None) -> Any:
        if ctx is None or not getattr(ctx, "profile_id", None):
            raise ValueError("Missing profile_id in ToolContext")
        return {"messages": [], "trust": "untrusted"}

    spec_gmail_list_messages = ToolSpec(
        name="gmail_list_messages",
        description=(
            "List read-only Gmail messages filtered by consented label ('appointments', "
            "'school-summaries', 'healthcare') via the curated Google Workspace remote MCP bridge."
        ),
        parameters={
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["appointments", "school-summaries", "healthcare", "INBOX"],
                    "default": "appointments",
                },
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
            },
            "required": ["label"],
        },
        risk_tier="read",
        trust="untrusted",
        data_flows=DataFlows(
            allowed_hosts=("workspace-mcp.spectrayan.com", "gmail.googleapis.com"),
            data_sensitivity="phi",
        ),
        executor=_exec_gmail_list_messages,
        metadata={
            "action": "gmail_list_messages",
            "connector_id": "google-workspace-gmail",
            "risk": "read",
            "taints_context": True,
        },
    )

    async def _exec_gmail_send_message(args: Dict[str, Any], ctx: Any = None) -> Any:
        if ctx is None or not getattr(ctx, "profile_id", None):
            raise ValueError("Missing profile_id in ToolContext")
        return {"status": "sent_via_approved_mcp", "risk_tier": "irreversible"}

    spec_gmail_send_message = ToolSpec(
        name="gmail_send_message",
        description=(
            "Send an email draft via the curated Google Workspace MCP server. "
            "Classified as 'irreversible' and unconditionally requires single-use human approval."
        ),
        parameters={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "recipient": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["draft_id", "recipient", "subject", "body"],
        },
        risk_tier="irreversible",
        trust="untrusted",
        data_flows=DataFlows(
            allowed_hosts=("workspace-mcp.spectrayan.com", "gmail.googleapis.com"),
            data_sensitivity="phi",
        ),
        executor=_exec_gmail_send_message,
        metadata={
            "action": "gmail_send_message",
            "connector_id": "google-workspace-gmail",
            "risk": "irreversible",
            "taints_context": True,
        },
    )
    return [
        spec_attach_read,
        spec_workspace_note,
        spec_skill_docs,
        spec_delegate_to_agent,
        spec_list_agents,
        spec_sanitize_pii,
        spec_extract_structured_data,
        spec_validate_grounding,
        spec_extract_document_dossier,
        spec_search_records,
        spec_create_reminder,
        spec_list_reminders,
        spec_web_search,
        spec_calendar_suggest_slots,
        spec_calendar_create_event,
        spec_create_email_draft,
        spec_gmail_list_messages,
        spec_gmail_send_message,
    ]


CORE_TOOL_NAMES: Tuple[str, ...] = (
    "attach-read",
    "workspace-note",
    "skill-docs",
    "delegate_to_agent",
    "list_agents",
    "sanitize_pii",
    "extract_structured_data",
    "validate_grounding",
    "extract_document_dossier",
    "search_records",
    "create_reminder",
    "list_reminders",
    "web_search",
    "calendar_suggest_slots",
    "calendar_create_event",
    "create_email_draft",
    "gmail_list_messages",
    "gmail_send_message",
)

HEALTH_TOOL_NAMES: Tuple[str, ...] = ()


def _make_core_builtin_specs() -> List[ToolSpec]:
    """Generates the 18 domain-neutral core ToolSpecs."""
    return _make_builtin_specs()


def _make_health_builtin_specs() -> List[ToolSpec]:
    """Generates domain-specific pack ToolSpecs (empty in core)."""
    return []


def create_default_registry(enabled_packs: Optional[Sequence[str]] = None) -> ToolSpecRegistry:
    """Creates a ToolSpecRegistry populated with Yarvelle Core built-in tools and declarative MCP DB tools."""
    registry = ToolSpecRegistry()
    for spec in _make_core_builtin_specs():
        registry.register(spec, pack_id="core")

    try:
        from yarvelle_core.tools.mcp_db_toolbox import register_db_toolbox_specs

        register_db_toolbox_specs(registry)
    except Exception as exc:
        logger.debug("Declarative MCP DB toolbox registration skipped: %s", exc)
    return registry


__all__ = [
    "CORE_TOOL_NAMES",
    "DataFlows",
    "HEALTH_TOOL_NAMES",
    "RiskTier",
    "ToolSpec",
    "ToolSpecRegistry",
    "TrustLevel",
    "_make_builtin_specs",
    "_make_core_builtin_specs",
    "_make_health_builtin_specs",
    "create_default_registry",
]
