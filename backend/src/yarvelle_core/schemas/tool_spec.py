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

"""Canonical versioned declarative tool specification models (`yarvelle.tools/v1`).

Provides the language-agnostic contract shared across Yarvelle Core, Python domain
packs, and sibling runtimes (modeled on Spector ADR-0025). Exported to JSON Schema
Draft 2020-12 at ``schemas/tool_spec.schema.json``.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Dict, FrozenSet, List, Literal, Optional, Union

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

API_VERSION_TOOLS_V1: Literal["yarvelle.tools/v1"] = "yarvelle.tools/v1"
KIND_TOOL_SET: Literal["ToolSet"] = "ToolSet"

TOOL_NAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
PYTHON_ENTRYPOINT_REGEX = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*:[a-zA-Z_][a-zA-Z0-9_]*$"
)

# Server-bound context parameters that must never appear in LLM-facing input_schema.
RESERVED_TOOL_CONTEXT_PARAMS: FrozenSet[str] = frozenset({
    "profile_id",
    "user_id",
    "locale",
    "now",
    "scope",
    "profile",
    "group_id",
    "run_id",
})

VALID_JSON_SCHEMA_TYPES: FrozenSet[str] = frozenset({
    "object",
    "array",
    "string",
    "integer",
    "number",
    "boolean",
    "null",
})

ToolRiskTier = Literal["read", "write_local", "write_external", "irreversible"]
ToolTrustLevel = Literal["trusted", "untrusted"]
ToolDataSensitivity = Literal[
    "public",
    "internal",
    "confidential",
    "restricted",
    "pii",
    "phi",
]


def _validate_json_schema_node(node: Any, path: str = "$") -> None:
    """Recursively validates a JSON Schema Draft 2020-12 node structure."""
    if not isinstance(node, dict):
        raise ValueError(f"{path}: JSON Schema node must be a mapping/dict, got {type(node).__name__}")

    schema_type = node.get("type")
    if schema_type is not None:
        if isinstance(schema_type, str):
            if schema_type not in VALID_JSON_SCHEMA_TYPES:
                raise ValueError(
                    f"{path}.type: invalid JSON Schema type '{schema_type}'; "
                    f"expected one of {sorted(VALID_JSON_SCHEMA_TYPES)}"
                )
        elif isinstance(schema_type, list):
            if not schema_type or not all(
                isinstance(t, str) and t in VALID_JSON_SCHEMA_TYPES for t in schema_type
            ):
                raise ValueError(
                    f"{path}.type: type union must be a non-empty list of valid JSON Schema types"
                )
        else:
            raise ValueError(f"{path}.type: must be a string or list of strings")

    if "enum" in node:
        enum_vals = node["enum"]
        if not isinstance(enum_vals, list) or len(enum_vals) == 0:
            raise ValueError(f"{path}.enum: must be a non-empty list")

    if "minimum" in node and "maximum" in node:
        minimum = node["minimum"]
        maximum = node["maximum"]
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
            if minimum > maximum:
                raise ValueError(
                    f"{path}: minimum ({minimum}) cannot exceed maximum ({maximum})"
                )

    if "minLength" in node and "maxLength" in node:
        min_len = node["minLength"]
        max_len = node["maxLength"]
        if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
            raise ValueError(
                f"{path}: minLength ({min_len}) cannot exceed maxLength ({max_len})"
            )

    if "properties" in node:
        props = node["properties"]
        if not isinstance(props, dict):
            raise ValueError(f"{path}.properties: must be an object mapping property names to schemas")
        for prop_name, prop_schema in props.items():
            if not isinstance(prop_name, str) or not prop_name.strip():
                raise ValueError(f"{path}.properties: property names must be non-empty strings")
            _validate_json_schema_node(prop_schema, f"{path}.properties.{prop_name}")

    if "required" in node:
        req = node["required"]
        if not isinstance(req, list) or not all(isinstance(r, str) and r.strip() for r in req):
            raise ValueError(f"{path}.required: must be a list of non-empty property names")
        if len(set(req)) != len(req):
            raise ValueError(f"{path}.required: contains duplicate property names")
        if isinstance(node.get("properties"), dict):
            missing_props = [r for r in req if r not in node["properties"]]
            if missing_props:
                raise ValueError(
                    f"{path}.required: references undeclared properties {missing_props}"
                )

    if "additionalProperties" in node:
        add_props = node["additionalProperties"]
        if not isinstance(add_props, bool):
            _validate_json_schema_node(add_props, f"{path}.additionalProperties")

    if "items" in node:
        items = node["items"]
        if isinstance(items, list):
            for idx, item_schema in enumerate(items):
                _validate_json_schema_node(item_schema, f"{path}.items[{idx}]")
        else:
            _validate_json_schema_node(items, f"{path}.items")

    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in node:
            branches = node[combinator]
            if not isinstance(branches, list) or len(branches) == 0:
                raise ValueError(f"{path}.{combinator}: must be a non-empty list of schemas")
            for idx, branch in enumerate(branches):
                _validate_json_schema_node(branch, f"{path}.{combinator}[{idx}]")

    if "$defs" in node:
        defs = node["$defs"]
        if not isinstance(defs, dict):
            raise ValueError(f"{path}.$defs: must be a mapping of schema definitions")
        for def_name, def_schema in defs.items():
            _validate_json_schema_node(def_schema, f"{path}.$defs.{def_name}")


def validate_tool_json_schema(
    schema: Dict[str, Any],
    *,
    require_object_root: bool = True,
    forbid_reserved_context_params: bool = True,
) -> Dict[str, Any]:
    """Validates an input or output JSON Schema for a declarative tool definition."""
    if not isinstance(schema, dict):
        raise ValueError("Schema must be a JSON object/dict.")

    if require_object_root:
        if schema.get("type") != "object":
            raise ValueError(
                f"Root tool schema must declare type 'object', got {schema.get('type')!r}."
            )
        if "properties" in schema and not isinstance(schema["properties"], dict):
            raise ValueError("Root tool schema 'properties' must be a mapping.")

    _validate_json_schema_node(schema, path="$")

    if forbid_reserved_context_params:
        props = schema.get("properties") or {}
        req = schema.get("required") or []
        leaked = sorted(
            (set(props.keys()) | set(req)) & RESERVED_TOOL_CONTEXT_PARAMS
        )
        if leaked:
            raise ValueError(
                f"Tool input_schema must not expose reserved server-bound context "
                f"parameters {leaked}; declare them in 'context_params' instead."
            )

    return schema


class HandlerToolBinding(BaseModel):
    """Binds a declarative tool to an async Python handler (`module:function`)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["handler"] = Field(default="handler", description="Python async handler binding")
    entrypoint: str = Field(
        ...,
        description="Importable async callable reference in 'package.module:function_name' format",
    )

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, v: str) -> str:
        clean = v.strip()
        if not PYTHON_ENTRYPOINT_REGEX.match(clean):
            raise ValueError(
                f"Invalid handler entrypoint '{v}': expected 'module.path:function_name'"
            )
        return clean


class SqlToolBinding(BaseModel):
    """Binds a declarative tool to a parameterized SQL statement."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sql"] = Field(default="sql", description="Parameterized SQL execution binding")
    source: str = Field(default="yarvelle-db", description="Configured SQL data source identifier")
    statement: str = Field(..., min_length=1, description="Parameterized SQL statement template")


class McpToolBinding(BaseModel):
    """Binds a declarative tool to a remote or stdio MCP server tool."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["mcp"] = Field(default="mcp", description="External MCP server tool binding")
    server_id: str = Field(..., min_length=1, description="Configured MCP server identifier")
    remote_tool: str = Field(..., min_length=1, description="Remote tool name exposed by the MCP server")
    expected_pin_hash: Optional[str] = Field(
        default=None,
        description="Optional cryptographic schema pin hash verifying tool contract integrity",
    )


class HttpToolBinding(BaseModel):
    """Binds a declarative tool to a ScopedHttp allowlisted request template."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["http"] = Field(default="http", description="Templated HTTP request binding")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(
        default="GET", description="HTTP method"
    )
    url_template: str = Field(..., min_length=1, description="HTTPS URL template")
    headers: Dict[str, str] = Field(default_factory=dict, description="Static or templated HTTP headers")
    body_template: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional JSON request body template"
    )


class PromptToolBinding(BaseModel):
    """Binds a declarative tool to a structured sub-LLM prompt template."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["prompt"] = Field(default="prompt", description="Prompt template execution binding")
    template: str = Field(..., min_length=1, description="Prompt template identifier or body")
    system: Optional[str] = Field(default=None, description="Optional system prompt override")
    max_output_tokens: Optional[int] = Field(
        default=None, ge=1, description="Maximum output tokens for prompt execution"
    )


class ComposeToolBinding(BaseModel):
    """Binds a declarative tool to a bounded sequence of composed tool invocations."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["compose"] = Field(default="compose", description="Macro composition binding")
    steps: List[Dict[str, Any]] = Field(
        ..., min_length=1, description="Ordered sequence of composed tool steps"
    )


ToolExecutionBinding = Annotated[
    Union[
        HandlerToolBinding,
        SqlToolBinding,
        McpToolBinding,
        HttpToolBinding,
        PromptToolBinding,
        ComposeToolBinding,
    ],
    Field(discriminator="kind"),
]


class DeclarativeToolSpec(BaseModel):
    """Canonical language-neutral specification of a single MCP or built-in tool."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(
        ...,
        validation_alias=AliasChoices("name", "id"),
        description="Unique canonical tool identifier (e.g. 'attach-read', 'list_reminders')",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="LLM-facing description explaining purpose, preconditions, and constraints",
    )
    category: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("category", "family"),
        description="Logical tool category or family (e.g. 'workspace', 'delegation', 'reminders')",
    )
    risk_tier: ToolRiskTier = Field(
        ...,
        description="4-tier execution gate classification ('read', 'write_local', 'write_external', 'irreversible')",
    )
    input_schema: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema Draft 2020-12 object schema for LLM-supplied arguments",
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional JSON Schema Draft 2020-12 schema for structured tool output",
    )
    binding: ToolExecutionBinding = Field(
        ...,
        description="Execution binding declaring how the runtime dispatches this tool",
    )
    pack_id: str = Field(
        default="core",
        min_length=1,
        description="Owning pack slug ('core' for built-in runtime tools)",
    )
    scopes: List[str] = Field(
        default_factory=list,
        description="Domain scopes required or touched by this tool",
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="Profile capability flags required to expose this tool",
    )
    data_sensitivity: ToolDataSensitivity = Field(
        default="internal",
        description="Data sensitivity classification driving redaction and egress policy",
    )
    trust: ToolTrustLevel = Field(
        default="trusted",
        description="Output provenance classification ('trusted' vs 'untrusted' taint source)",
    )
    allowed_hosts: List[str] = Field(
        default_factory=list,
        description="Outbound network host allowlist enforced by ScopedHttp / EgressFirewall",
    )
    allowed_methods: List[str] = Field(
        default_factory=lambda: ["GET", "POST"],
        description="Allowed HTTP methods when outbound hosts are declared",
    )
    context_params: List[str] = Field(
        default_factory=list,
        description="Server-bound context parameters injected by the runtime (never LLM-controlled)",
    )
    phase_0_closed: bool = Field(
        default=False,
        description="Whether this tool belongs to the Phase 0 default sandboxed closed tool set",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional policy and UI trace metadata (entity, action, undoable, connector_id)",
    )

    @property
    def id(self) -> str:
        """Alias matching pack manifest and sibling Rust runtime conventions."""
        return self.name

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not TOOL_NAME_REGEX.match(clean):
            raise ValueError(
                f"Invalid tool name '{v}': must match {TOOL_NAME_REGEX.pattern}"
            )
        return clean

    @field_validator("description", "category", "pack_id")
    @classmethod
    def validate_non_empty_trimmed(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Field must not be empty or whitespace-only.")
        return clean

    @field_validator("context_params")
    @classmethod
    def validate_context_params(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in v:
            param = str(item).strip()
            if not param:
                raise ValueError("context_params entries must be non-empty strings.")
            if param not in RESERVED_TOOL_CONTEXT_PARAMS:
                raise ValueError(
                    f"Unsupported context_params entry '{param}'; "
                    f"allowed server-bound parameters: {sorted(RESERVED_TOOL_CONTEXT_PARAMS)}"
                )
            if param not in cleaned:
                cleaned.append(param)
        return cleaned

    @field_validator("input_schema")
    @classmethod
    def validate_input_schema_field(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        return validate_tool_json_schema(
            v,
            require_object_root=True,
            forbid_reserved_context_params=True,
        )

    @field_validator("output_schema")
    @classmethod
    def validate_output_schema_field(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        return validate_tool_json_schema(
            v,
            require_object_root=False,
            forbid_reserved_context_params=False,
        )

    def sanitized_input_schema(self) -> Dict[str, Any]:
        """Returns a defensive copy of input_schema with any server-bound context keys stripped."""
        schema = dict(self.input_schema)
        excluded = set(self.context_params) | RESERVED_TOOL_CONTEXT_PARAMS
        if isinstance(schema.get("properties"), dict):
            schema["properties"] = {
                k: v for k, v in schema["properties"].items() if k not in excluded
            }
        if isinstance(schema.get("required"), list):
            schema["required"] = [r for r in schema["required"] if r not in excluded]
            if not schema["required"]:
                schema.pop("required", None)
        return schema

    def to_tool_definition(self) -> Dict[str, Any]:
        """Returns an OpenAI / LangChain bind_tools-compatible dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.sanitized_input_schema(),
        }

    def to_mcp_tool_descriptor(self) -> Dict[str, Any]:
        """Returns an MCP 2024-11-05 `tools/list` compatible tool descriptor."""
        descriptor: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.sanitized_input_schema(),
        }
        if self.output_schema is not None:
            descriptor["outputSchema"] = dict(self.output_schema)
        return descriptor


class ToolSetManifest(BaseModel):
    """Versioned declarative tool-set resource document (`apiVersion: yarvelle.tools/v1`)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    api_version: Literal["yarvelle.tools/v1"] = Field(
        default=API_VERSION_TOOLS_V1,
        alias="apiVersion",
        serialization_alias="apiVersion",
        description="Declarative tool specification API version",
    )
    kind: Literal["ToolSet"] = Field(
        default=KIND_TOOL_SET,
        description="Resource document kind discriminator",
    )
    pack_id: str = Field(
        default="core",
        min_length=1,
        description="Default owning pack identifier for tools declared in this file",
    )
    tools: List[DeclarativeToolSpec] = Field(
        default_factory=list,
        description="Declarative tool specifications defined in this manifest",
    )

    @model_validator(mode="after")
    def validate_unique_names_and_pack_defaults(self) -> ToolSetManifest:
        seen: set[str] = set()
        updated_tools: List[DeclarativeToolSpec] = []
        for spec in self.tools:
            if spec.name in seen:
                raise ValueError(f"Duplicate tool name '{spec.name}' in ToolSetManifest.")
            seen.add(spec.name)
            if spec.pack_id == "core" and self.pack_id != "core":
                spec = spec.model_copy(update={"pack_id": self.pack_id})
            updated_tools.append(spec)
        object.__setattr__(self, "tools", updated_tools)
        return self


__all__ = [
    "API_VERSION_TOOLS_V1",
    "ComposeToolBinding",
    "DeclarativeToolSpec",
    "HandlerToolBinding",
    "HttpToolBinding",
    "KIND_TOOL_SET",
    "McpToolBinding",
    "PromptToolBinding",
    "RESERVED_TOOL_CONTEXT_PARAMS",
    "SqlToolBinding",
    "ToolDataSensitivity",
    "ToolExecutionBinding",
    "ToolRiskTier",
    "ToolSetManifest",
    "ToolTrustLevel",
    "VALID_JSON_SCHEMA_TYPES",
    "validate_tool_json_schema",
]
