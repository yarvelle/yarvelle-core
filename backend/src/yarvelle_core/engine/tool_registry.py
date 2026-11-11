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
- ToolSpecRegistry: Tool catalog with age-band, capability, and pack filtering
- create_default_registry: Factory populating declarative Yarvelle Core built-in, DB, and enabled pack tools
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.metadata
import logging
from typing import (
    Any,
    Callable,
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

from yarvelle_core.schemas.age_band import CHILD_UNDER_13, canonical_age_band
from yarvelle_core.scope.context import DEFAULT_SCOPE
from yarvelle_core.tools.spec_loader import (
    BoundDeclarativeTool,
    ToolSpecLoader,
    get_tool_spec_loader,
)

logger = logging.getLogger("yarvelle_core.engine.tool_registry")

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
    data_sensitivity: str = "internal"  # "public", "internal", "confidential", "restricted", "pii"

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
        if self.executor is not None and self.handler is None:
            object.__setattr__(self, "handler", self.executor)
        elif self.handler is not None and self.executor is None:
            object.__setattr__(self, "executor", self.handler)

        if not isinstance(self.data_flows, DataFlows):
            normalized = _normalize_data_flows(self.data_flows)
            object.__setattr__(self, "data_flows", normalized)

        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})

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
        """Registers or updates a tool specification in the registry."""
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
        """Filters registered tools based on profile age band and capability constraints."""
        effective_age_band = canonical_age_band(age_band)
        effective_consents = consents or {}
        has_guardian_consent = bool(effective_consents.get("guardian_consent") is True)
        enabled_caps = set(capabilities or ())

        allowed: List[ToolSpec] = []

        for spec in self._tools.values():
            required_caps = spec.metadata.get("required_capabilities")
            if required_caps:
                if not any(rc in enabled_caps for rc in required_caps):
                    continue

            if effective_age_band == CHILD_UNDER_13:
                if spec.risk_tier == "write_external":
                    continue
                if spec.trust == "untrusted":
                    continue
                if spec.risk_tier == "write_local" and not has_guardian_consent:
                    continue
                if spec.risk_tier == "irreversible":
                    continue

            allowed.append(spec)

        return allowed


# ============================================================================
# Declarative ToolSpec Conversion & Registry Factory
# ============================================================================

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


def bound_declarative_to_tool_spec(bound: BoundDeclarativeTool) -> ToolSpec:
    """Converts a validated ``BoundDeclarativeTool`` into a runtime ``ToolSpec``."""
    decl = bound.spec
    meta: Dict[str, Any] = dict(decl.metadata)
    meta.setdefault("category", decl.category)
    if decl.capabilities and "required_capabilities" not in meta:
        meta["required_capabilities"] = list(decl.capabilities)
    if decl.output_schema is not None and "output_schema" not in meta:
        meta["output_schema"] = dict(decl.output_schema)
    if decl.context_params and "context_params" not in meta:
        meta["context_params"] = list(decl.context_params)

    return ToolSpec(
        name=decl.name,
        description=decl.description,
        parameters=decl.sanitized_input_schema(),
        risk_tier=decl.risk_tier,
        trust=decl.trust,
        data_flows=DataFlows(
            allowed_hosts=tuple(decl.allowed_hosts),
            allowed_methods=tuple(decl.allowed_methods),
            data_sensitivity=decl.data_sensitivity,
        ),
        executor=bound.executor,
        metadata=meta,
        scopes=set(decl.scopes) if decl.scopes else set(),
    )


def _make_builtin_specs(loader: Optional[ToolSpecLoader] = None) -> List[ToolSpec]:
    """Loads all built-in Yarvelle Core ToolSpecs from declarative YAML resources."""
    active_loader = loader or get_tool_spec_loader()
    by_name: Dict[str, ToolSpec] = {
        item.spec.name: bound_declarative_to_tool_spec(item)
        for item in active_loader.load_core_tools()
    }
    ordered: List[ToolSpec] = []
    for canonical_name in CORE_TOOL_NAMES:
        if canonical_name in by_name:
            ordered.append(by_name.pop(canonical_name))
    for remaining_name in sorted(by_name.keys()):
        ordered.append(by_name[remaining_name])
    return ordered


def _make_core_builtin_specs(loader: Optional[ToolSpecLoader] = None) -> List[ToolSpec]:
    """Loads all domain-neutral Yarvelle Core built-in ToolSpecs."""
    return _make_builtin_specs(loader=loader)


def _make_health_builtin_specs() -> List[ToolSpec]:
    """Deprecated compatibility shim; domain pack tools belong in external packs."""
    return []


def _load_entrypoint_pack_tools(
    registry: ToolSpecRegistry,
    enabled_packs: Optional[Sequence[str]],
) -> None:
    """Registers tools exposed by installed `yarvelle.packs` entry points matching `enabled_packs`."""
    try:
        discovered_eps = importlib.metadata.entry_points(group="yarvelle.packs")
    except TypeError:
        all_eps = importlib.metadata.entry_points()
        discovered_eps = all_eps.get("yarvelle.packs", [])

    allowed_ids: Optional[Set[str]] = (
        {p.strip().lower() for p in enabled_packs if p and p.strip()}
        if enabled_packs is not None
        else None
    )

    for ep in discovered_eps:
        pack_id = ep.name.strip().lower()
        if allowed_ids is not None and pack_id not in allowed_ids:
            continue
        try:
            factory = ep.load()
            if callable(factory):
                pack_spec = factory()
                for tool in getattr(pack_spec, "tools", ()) or ():
                    if isinstance(tool, ToolSpec):
                        registry.register(tool, pack_id=pack_id)
        except Exception as exc:
            logger.debug("Skipping entry-point pack '%s' tool registration: %s", pack_id, exc)


def create_default_registry(
    enabled_packs: Optional[Sequence[str]] = None,
    *,
    loader: Optional[ToolSpecLoader] = None,
) -> ToolSpecRegistry:
    """Creates a ToolSpecRegistry populated with core built-ins, DB tools, and enabled pack tools.

    Args:
        enabled_packs: Optional sequence of enabled pack slugs. When None, core tools and
            all registered pack tools are included. When provided (including an empty
            sequence ``[]``), pack-scoped tools are filtered strictly to ``enabled_packs``.
        loader: Optional explicit ``ToolSpecLoader`` override (defaults to singleton loader).
    """
    active_loader = loader or get_tool_spec_loader()
    registry = ToolSpecRegistry()

    for spec in _make_core_builtin_specs(loader=active_loader):
        registry.register(spec, pack_id="core")

    try:
        from yarvelle_core.tools.mcp_db_toolbox import register_db_toolbox_specs

        register_db_toolbox_specs(registry)
    except Exception as exc:
        logger.debug("Declarative MCP DB toolbox registration skipped: %s", exc)

    # Register declarative pack tools filtered by enabled_packs
    for item in active_loader.load_enabled_tools(enabled_packs=enabled_packs):
        if item.spec.pack_id == "core":
            continue
        registry.register(bound_declarative_to_tool_spec(item), pack_id=item.spec.pack_id)

    # Register installed entry-point pack tools filtered by enabled_packs
    _load_entrypoint_pack_tools(registry, enabled_packs=enabled_packs)

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
    "bound_declarative_to_tool_spec",
    "create_default_registry",
]
