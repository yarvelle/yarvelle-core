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

"""Build-time contract tests for declarative MCP & built-in tool specifications.

Modeled on Spector ADR-0025 (`McpToolSchemaValidationTest`):
1. Every declarative YAML/JSON tool spec validates against `schemas/tool_spec.schema.json`.
2. Every `kind: handler` spec resolves to a registered async coroutine callable.
3. Strict 1:1 parity holds between declarative core specs and `@builtin_tool_handler`
   functions in `yarvelle_core.tools.builtin_handlers` (zero missing or orphaned handlers).
4. Reserved server-bound context parameters (`profile_id`, `user_id`, `locale`, `now`, `scope`)
   are strictly rejected in LLM-facing `input_schema`.
5. `CLOSED_TOOL_DEFINITIONS`, `ClosedToolName`, `CORE_TOOL_NAMES`, and `create_default_registry`
   are derived from and consistent with the canonical declarative catalog.
6. `create_default_registry(enabled_packs=...)` filters pack-contributed tools deterministically.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Dict, get_args
import pytest

from yarvelle_core.engine.tool_registry import (
    CORE_TOOL_NAMES,
    _make_core_builtin_specs,
    create_default_registry,
)
from yarvelle_core.schemas.tool import CLOSED_TOOL_NAMES, ClosedToolName
from yarvelle_core.schemas.tool_spec import (
    API_VERSION_TOOLS_V1,
    HandlerToolBinding,
    RESERVED_TOOL_CONTEXT_PARAMS,
    ToolSetManifest,
    validate_tool_json_schema,
)
from yarvelle_core.tools import builtin_handlers
from yarvelle_core.tools.builtin_handlers import BUILTIN_TOOL_HANDLERS
from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS, get_closed_tool
from yarvelle_core.tools.spec_loader import (
    DEFAULT_CORE_TOOLS_DIR,
    ToolSpecLoader,
    ToolSpecValidationError,
)


def test_committed_tool_spec_json_schema_exists_and_documents_contract():
    """Verify schemas/tool_spec.schema.json is committed, valid Draft 2020-12, and synchronized."""
    repo_root = Path(__file__).resolve().parents[2]
    top_schema_path = repo_root / "schemas" / "tool_spec.schema.json"
    pkg_schema_path = (
        repo_root / "backend" / "src" / "yarvelle_core" / "schemas" / "tool_spec.schema.json"
    )

    assert top_schema_path.is_file(), f"Missing {top_schema_path}"
    assert pkg_schema_path.is_file(), f"Missing {pkg_schema_path}"

    top_raw = top_schema_path.read_text(encoding="utf-8")
    pkg_raw = pkg_schema_path.read_text(encoding="utf-8")
    assert top_raw == pkg_raw

    schema = json.loads(top_raw)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://schemas.yarvelle.org/v1/tool_spec.schema.json"
    assert "apiVersion" in schema["properties"]
    assert "tools" in schema["properties"]
    assert "DeclarativeToolSpec" in schema.get("$defs", {})


def test_all_core_declarative_specs_validate_and_match_handlers_one_to_one():
    """Verify 1:1 parity between declarative YAML specs and Python async handlers."""
    loader = ToolSpecLoader()
    core_items = loader.load_core_tools()

    assert len(core_items) == 18
    loaded_names = [item.spec.name for item in core_items]
    assert set(loaded_names) == set(CORE_TOOL_NAMES)

    # 1. Every declarative spec has valid input/output schema, valid risk tier, and async handler
    resolved_handlers: Dict[str, Any] = {}
    for item in core_items:
        spec = item.spec
        validate_tool_json_schema(spec.input_schema, require_object_root=True)
        if spec.output_schema is not None:
            validate_tool_json_schema(
                spec.output_schema,
                require_object_root=False,
                forbid_reserved_context_params=False,
            )
        assert isinstance(spec.binding, HandlerToolBinding)
        assert item.executor is not None, f"Spec '{spec.name}' failed to bind an executor"
        assert inspect.iscoroutinefunction(item.executor), (
            f"Executor for '{spec.name}' must be async"
        )
        assert spec.name in BUILTIN_TOOL_HANDLERS, (
            f"Declarative tool '{spec.name}' is not registered in BUILTIN_TOOL_HANDLERS"
        )
        assert item.executor is BUILTIN_TOOL_HANDLERS[spec.name]
        resolved_handlers[spec.name] = item.executor

    # 2. Zero orphaned handlers in BUILTIN_TOOL_HANDLERS
    orphaned_registered = set(BUILTIN_TOOL_HANDLERS.keys()) - set(resolved_handlers.keys())
    assert not orphaned_registered, (
        f"Orphaned handlers in BUILTIN_TOOL_HANDLERS without declarative specs: {sorted(orphaned_registered)}"
    )

    # 3. Zero undecorated `exec_*` functions in builtin_handlers module
    module_exec_fns = {
        fn_obj
        for fn_name, fn_obj in inspect.getmembers(builtin_handlers, inspect.isfunction)
        if fn_name.startswith("exec_")
    }
    registered_fn_objs = set(BUILTIN_TOOL_HANDLERS.values())
    unregistered_fns = [fn.__name__ for fn in module_exec_fns if fn not in registered_fn_objs]
    assert not unregistered_fns, (
        f"Found exec_* functions in builtin_handlers.py missing @builtin_tool_handler: {unregistered_fns}"
    )


def test_core_yaml_files_contain_no_stale_python_toolspec_bloat():
    """Verify engine/tool_registry.py no longer embeds stale docstrings or inline tool catalogs."""
    repo_root = Path(__file__).resolve().parents[2]
    registry_py = (
        repo_root / "backend" / "src" / "yarvelle_core" / "engine" / "tool_registry.py"
    ).read_text(encoding="utf-8")

    assert "all 9 Yarvelle Core built-in tools" not in registry_py
    yaml_files = sorted(DEFAULT_CORE_TOOLS_DIR.glob("*.yaml"))
    assert len(yaml_files) >= 1
    for yf in yaml_files:
        parsed = ToolSpecLoader().load_file(yf)
        assert len(parsed) >= 1


def test_closed_tool_definitions_and_closed_tool_name_have_zero_drift():
    """Verify CLOSED_TOOL_DEFINITIONS and ClosedToolName match the canonical catalog."""
    expected_closed = {"attach-read", "workspace-note", "skill-docs", "search_records"}
    assert set(get_args(ClosedToolName)) == expected_closed
    assert set(CLOSED_TOOL_NAMES) == expected_closed
    assert set(CLOSED_TOOL_DEFINITIONS.keys()) == expected_closed

    core_specs_by_name = {s.name: s for s in _make_core_builtin_specs()}
    for name in expected_closed:
        core_def = core_specs_by_name[name].to_tool_definition()
        closed_def = get_closed_tool(name)
        assert closed_def == core_def
        assert CLOSED_TOOL_DEFINITIONS[name] == core_def


@pytest.mark.parametrize("reserved_param", sorted(RESERVED_TOOL_CONTEXT_PARAMS))
def test_loader_rejects_reserved_context_parameters_in_input_schema(
    tmp_path: Path, reserved_param: str
):
    """Reserved context parameters must never be controllable via LLM input_schema."""
    bad_file = tmp_path / "bad_reserved.yaml"
    bad_file.write_text(
        json.dumps(
            {
                "apiVersion": API_VERSION_TOOLS_V1,
                "kind": "ToolSet",
                "tools": [
                    {
                        "name": "leaked_context_tool",
                        "description": "Attempts to expose server-bound context parameter.",
                        "category": "workspace",
                        "risk_tier": "read",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                reserved_param: {"type": "string"},
                            },
                            "required": ["query"],
                        },
                        "binding": {
                            "kind": "handler",
                            "entrypoint": "yarvelle_core.tools.builtin_handlers:exec_list_agents",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loader = ToolSpecLoader()
    with pytest.raises(ToolSpecValidationError, match="reserved server-bound context"):
        loader.load_file(bad_file)


def test_loader_rejects_invalid_json_schemas_and_bad_handlers(tmp_path: Path):
    """Verify malformed JSON Schemas, invalid risk tiers, and non-async handlers fail closed."""
    loader = ToolSpecLoader()

    # 1. Invalid JSON Schema type
    bad_schema_file = tmp_path / "bad_schema.json"
    bad_schema_file.write_text(
        json.dumps(
            {
                "apiVersion": API_VERSION_TOOLS_V1,
                "kind": "ToolSet",
                "tools": [
                    {
                        "name": "invalid_schema_tool",
                        "description": "Has an invalid JSON Schema property type.",
                        "category": "workspace",
                        "risk_tier": "read",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "count": {"type": "not_a_valid_type"},
                            },
                        },
                        "binding": {
                            "kind": "handler",
                            "entrypoint": "yarvelle_core.tools.builtin_handlers:exec_list_agents",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolSpecValidationError, match="invalid JSON Schema type"):
        loader.load_file(bad_schema_file)

    # 2. Required property missing from properties map
    bad_req_file = tmp_path / "bad_req.json"
    bad_req_file.write_text(
        json.dumps(
            {
                "apiVersion": API_VERSION_TOOLS_V1,
                "kind": "ToolSet",
                "tools": [
                    {
                        "name": "missing_required_prop",
                        "description": "Lists undeclared required key.",
                        "category": "workspace",
                        "risk_tier": "read",
                        "input_schema": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}},
                            "required": ["title", "ghost_field"],
                        },
                        "binding": {
                            "kind": "handler",
                            "entrypoint": "yarvelle_core.tools.builtin_handlers:exec_list_agents",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolSpecValidationError, match="undeclared properties"):
        loader.load_file(bad_req_file)

    # 3. Missing/non-existent handler entrypoint
    bad_handler_file = tmp_path / "bad_handler.json"
    bad_handler_file.write_text(
        json.dumps(
            {
                "apiVersion": API_VERSION_TOOLS_V1,
                "kind": "ToolSet",
                "tools": [
                    {
                        "name": "missing_handler_tool",
                        "description": "Points to non-existent callable.",
                        "category": "workspace",
                        "risk_tier": "read",
                        "input_schema": {"type": "object", "properties": {}},
                        "binding": {
                            "kind": "handler",
                            "entrypoint": "yarvelle_core.tools.builtin_handlers:does_not_exist",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolSpecValidationError, match="does not exist or is not callable"):
        loader.load_file(bad_handler_file)


def test_loader_caching_and_single_tool_json_support(tmp_path: Path):
    """Verify ToolSpecLoader caches core specs and supports single-tool JSON files (ADR-0025)."""
    loader = ToolSpecLoader()
    first = loader.load_core_tools()
    second = loader.load_core_tools()
    assert first is second

    loader.clear_cache()
    third = loader.load_core_tools()
    assert third is not first
    assert [t.spec.name for t in third] == [t.spec.name for t in first]

    # Single-tool JSON object format
    single_json = tmp_path / "single_tool.json"
    single_json.write_text(
        json.dumps(
            {
                "id": "pack_ping",
                "description": "Lightweight pack connectivity check.",
                "family": "diagnostics",
                "risk_tier": "read",
                "input_schema": {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                },
                "binding": {
                    "kind": "mcp",
                    "server_id": "local-diag",
                    "remote_tool": "ping",
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = loader.load_file(single_json, default_pack_id="household")
    assert len(loaded) == 1
    assert loaded[0].spec.name == "pack_ping"
    assert loaded[0].spec.id == "pack_ping"
    assert loaded[0].spec.category == "diagnostics"
    assert loaded[0].spec.pack_id == "household"
    mcp_desc = loaded[0].spec.to_mcp_tool_descriptor()
    assert mcp_desc["name"] == "pack_ping"
    assert "inputSchema" in mcp_desc
    assert "outputSchema" in mcp_desc


def test_create_default_registry_filters_by_enabled_packs(tmp_path: Path):
    """Verify create_default_registry(enabled_packs=...) filters pack-scoped declarative tools."""
    loader = ToolSpecLoader()

    finance_yaml = tmp_path / "finance_tools.yaml"
    finance_yaml.write_text(
        """
apiVersion: yarvelle.tools/v1
kind: ToolSet
pack_id: finance
tools:
  - name: ledger_balance_summary
    category: ledger
    risk_tier: read
    scopes: [finance.accounts]
    description: Summarize account balances for the active profile.
    input_schema:
      type: object
      properties:
        currency:
          type: string
          default: USD
    binding:
      kind: handler
      entrypoint: yarvelle_core.tools.builtin_handlers:exec_list_agents
""",
        encoding="utf-8",
    )

    travel_yaml = tmp_path / "travel_tools.yaml"
    travel_yaml.write_text(
        """
apiVersion: yarvelle.tools/v1
kind: ToolSet
pack_id: travel
tools:
  - name: itinerary_lookup
    category: planning
    risk_tier: read
    scopes: [travel.trips]
    description: Retrieve saved trip itineraries for the active profile.
    input_schema:
      type: object
      properties:
        destination:
          type: string
    binding:
      kind: handler
      entrypoint: yarvelle_core.tools.builtin_handlers:exec_list_agents
""",
        encoding="utf-8",
    )

    loader.register_pack_source("finance", finance_yaml)
    loader.register_pack_source("travel", travel_yaml)

    # 1. Explicit empty list -> core tools only
    reg_core_only = create_default_registry(enabled_packs=[], loader=loader)
    assert reg_core_only.get("attach-read") is not None
    assert reg_core_only.get("ledger_balance_summary") is None
    assert reg_core_only.get("itinerary_lookup") is None

    # 2. Only 'finance' enabled -> core + finance, excluding travel
    reg_finance = create_default_registry(enabled_packs=["finance"], loader=loader)
    assert reg_finance.get("attach-read") is not None
    assert reg_finance.get("ledger_balance_summary") is not None
    assert reg_finance.get_pack_id("ledger_balance_summary") == "finance"
    assert reg_finance.get("itinerary_lookup") is None

    # 3. enabled_packs=None -> core + all registered packs
    reg_all = create_default_registry(enabled_packs=None, loader=loader)
    assert reg_all.get("ledger_balance_summary") is not None
    assert reg_all.get("itinerary_lookup") is not None
