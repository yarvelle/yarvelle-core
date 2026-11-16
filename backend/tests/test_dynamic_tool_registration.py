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

"""Unit tests for dynamic pack tool registration and validation (Issue #64)."""

from __future__ import annotations

from pathlib import Path
import pytest

from yarvelle_core.loaders.union import (
    ToolValidationError,
    compute_effective_tools,
    validate_tools_against_registry,
    validate_tools_in_phase0,
)
from yarvelle_core.loaders.agent_loader import load_agent_from_record
from yarvelle_core.schemas.manifest import PHASE_0_REGISTRY, SkillManifest, RiskClass, AgentDomain


def test_validate_tools_against_registry_fallback_to_phase0():
    """When allowed_tools is None, validation strictly checks PHASE_0_REGISTRY."""
    # Valid Phase 0 tools should pass
    validate_tools_against_registry(["attach-read", "workspace-note"])
    validate_tools_in_phase0(["attach-read", "workspace-note"])

    # Unregistered tool should raise ToolValidationError
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tools_against_registry(["custom_pack_tool_x"])
    assert "not in Phase 0 closed registry" in str(exc_info.value)

    with pytest.raises(ToolValidationError):
        validate_tools_in_phase0(["custom_pack_tool_x"])


def test_validate_tools_against_registry_custom_allowlist():
    """When allowed_tools is provided, tools are validated against that specific set."""
    custom_allowed = {"tool_alpha", "tool_beta", "workspace-note"}

    # Tools in custom_allowed pass
    validate_tools_against_registry(["tool_alpha", "workspace-note"], allowed_tools=custom_allowed)

    # Tool not in custom_allowed fails even if in PHASE_0_REGISTRY
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tools_against_registry(["attach-read"], allowed_tools=custom_allowed)
    assert "not in registered toolset" in str(exc_info.value)


def test_compute_effective_tools_fallback_and_dynamic():
    """Test compute_effective_tools with fallback and explicit allowed_tools."""
    agent_tools = ["workspace-note", "custom_pack_tool"]
    dummy_skill = SkillManifest(
        id="test-skill",
        name="test-skill",
        title="Test Skill",
        description="A test skill",
        version="1.0.0",
        license="MIT",
        risk_class=RiskClass.WELLNESS,
        domain=AgentDomain.GENERAL,
        category="testing",
        tags=["test"],
        tools=["skill_tool_x", "attach-read"],
        instructions="Instructions here.",
        is_verified=True,
    )

    # Fallback to Phase 0: only workspace-note and attach-read survive
    effective_default = compute_effective_tools(agent_tools, [dummy_skill])
    assert "workspace-note" in effective_default
    assert "attach-read" in effective_default
    assert "custom_pack_tool" not in effective_default
    assert "skill_tool_x" not in effective_default

    # Dynamic registry allowlist
    custom_allowed = {"workspace-note", "custom_pack_tool", "skill_tool_x"}
    effective_custom = compute_effective_tools(agent_tools, [dummy_skill], allowed_tools=custom_allowed)
    assert "workspace-note" in effective_custom
    assert "custom_pack_tool" in effective_custom
    assert "skill_tool_x" in effective_custom
    assert "attach-read" not in effective_custom


def test_load_agent_from_record_with_allowed_tools():
    """Test load_agent_from_record with custom allowed_tools."""
    record = {
        "id": "custom-agent",
        "title": "Custom Agent",
        "role": "General Assistant",
        "model": "ollama:llama3.2",
        "persona": "Test persona text with enough characters to be valid.",
        "tools": ["pack_tool_one", "workspace-note"],
    }

    # Should fail if allowed_tools is None (fallback to Phase 0)
    with pytest.raises(ToolValidationError):
        load_agent_from_record(record)

    # Should succeed when pack_tool_one is allowed
    custom_allowed = {"pack_tool_one", "workspace-note"}
    agent, eff_tools, skills = load_agent_from_record(record, allowed_tools=custom_allowed)
    assert agent.id == "custom-agent"
    assert "pack_tool_one" in eff_tools
    assert "workspace-note" in eff_tools


def test_filesystem_agent_source_uses_registered_tools_and_rejects_unknown(tmp_path: Path):
    """FilesystemAgentSource accepts registered default-registry tools and rejects unregistered ones."""
    from yarvelle_core.agents.sources import FilesystemAgentSource
    from yarvelle_core.engine.tool_registry import create_default_registry
    from yarvelle_core.tools.spec_loader import normalize_enabled_pack_ids

    class _PackRef:
        def __init__(self, pack_id: str) -> None:
            self.id = pack_id

    assert normalize_enabled_pack_ids([_PackRef("core"), "CustomPack"]) == {"core", "custompack"}
    reg = create_default_registry(enabled_packs=[_PackRef("core")])
    assert reg.get("workspace-note") is not None

    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)

    valid_dir = agents_dir / "valid-agent"
    valid_dir.mkdir(parents=True)
    (valid_dir / "agent.yaml").write_text(
        "name: valid-agent\n"
        "description: Uses registered workspace note tool\n"
        "tools:\n"
        "  - workspace-note\n"
        "  - create_workspace_note\n",
        encoding="utf-8",
    )
    (valid_dir / "persona.md").write_text("Helpful domain-neutral workspace assistant.", encoding="utf-8")

    invalid_dir = agents_dir / "invalid-agent"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "agent.yaml").write_text(
        "name: invalid-agent\n"
        "description: Declares unregistered tool\n"
        "tools:\n"
        "  - unregistered_shell_exec\n",
        encoding="utf-8",
    )
    (invalid_dir / "persona.md").write_text("Assistant with unregistered tool.", encoding="utf-8")

    res = FilesystemAgentSource(agents_dir, skills_dir).load()
    loaded_ids = [r.manifest.id for r in res.records]
    rejected_ids = [r.agent_id for r in res.rejected]
    assert "valid-agent" in loaded_ids
    assert "invalid-agent" in rejected_ids


def test_json_schema_to_args_model_preserves_anyof_and_nested_objects():
    """_json_schema_to_args_model unwraps anyOf nullable types, typed arrays, and nested object schemas."""
    from yarvelle_core.workflows.nodes.main_agent_node import _json_schema_to_args_model, _to_plain_value

    schema = {
        "type": "object",
        "required": ["label", "payload"],
        "properties": {
            "label": {"type": "string", "description": "Item label"},
            "limit_amount": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "description": "Numeric limit",
            },
            "labels": {
                "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                "default": None,
                "description": "Optional list of tags",
            },
            "payload": {
                "type": "object",
                "description": "Structured nested inputs",
                "properties": {
                    "reading_a": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
                    "count_b": {"type": "integer", "description": "Count metric"},
                },
            },
            "_count": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "description": "Leading-underscore query limit",
            },
        },
    }
    args_model = _json_schema_to_args_model("nested_demo", schema)
    instance = args_model(
        label="test",
        limit_amount=42.5,
        labels=["alpha", "beta"],
        payload={"reading_a": 12.5, "count_b": 3},
        _count=10,
    )
    plain = _to_plain_value(instance)
    assert plain["limit_amount"] == 42.5
    assert plain["labels"] == ["alpha", "beta"]
    assert plain["payload"] == {"reading_a": 12.5, "count_b": 3}
    assert plain["_count"] == 10
    import json

    serialized_schema = json.dumps(args_model.model_json_schema())
    assert "reading_a" in serialized_schema
    assert "count_b" in serialized_schema


@pytest.mark.asyncio
async def test_agent_execution_schema_simplification_bracket_repair_and_empty_retry(tmp_path: Path):
    """Covers LLM nullable schema flattening, malformed JSON bracket repair, and empty-response retry."""
    from langchain_core.messages import AIMessage, HumanMessage

    from yarvelle_core.agents.registry import AgentRegistry
    from yarvelle_core.engine.tool_registry import ToolSpec, ToolSpecRegistry
    from yarvelle_core.workflows.nodes.agent_execution_node import (
        AgentExecutionNode,
        _parse_fallback_tool_calls,
        _serialize_tool_for_binding,
    )

    spec = ToolSpec(
        name="record_metrics",
        description="Store structured metric observations",
        parameters={
            "type": "object",
            "required": ["metrics"],
            "properties": {
                "metrics": {
                    "type": "object",
                    "properties": {
                        "alpha": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
                        "beta": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
                    },
                },
                "labels": {
                    "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                    "description": "Optional label strings",
                },
            },
        },
        risk_tier="write_local",
    )
    serialized = _serialize_tool_for_binding(spec)
    assert serialized["parameters"]["properties"]["labels"]["type"] == "array"
    assert "anyOf" not in serialized["parameters"]["properties"]["labels"]
    assert serialized["parameters"]["properties"]["metrics"]["properties"]["alpha"]["type"] == "number"
    # Original ToolSpec.parameters must remain untouched for schema parity checks.
    assert "anyOf" in spec.parameters["properties"]["labels"]

    malformed = (
        "```tool_code\n"
        '{"tool_calls": [{"name": "record_metrics", "args": {"metrics": {"alpha": 10, "beta": 20}}}}\n'
        "```"
    )
    parsed = _parse_fallback_tool_calls(malformed, {"record_metrics"})
    assert len(parsed) == 1
    assert parsed[0]["name"] == "record_metrics"
    assert parsed[0]["args"] == {"metrics": {"alpha": 10, "beta": 20}}
    assert _parse_fallback_tool_calls(malformed, {"other_tool"}) == []

    agents_dir = tmp_path / "agents"
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    demo_dir = agents_dir / "metrics-assistant"
    demo_dir.mkdir(parents=True)
    (demo_dir / "agent.yaml").write_text(
        "name: metrics-assistant\n"
        "description: Records structured workspace metrics\n"
        "tools:\n"
        "  - workspace-note\n",
        encoding="utf-8",
    )
    (demo_dir / "persona.md").write_text("Helpful domain-neutral metrics organizer.", encoding="utf-8")

    class _EmptyBoundThenTextModel:
        def __init__(self, *, is_bound: bool = False) -> None:
            self.is_bound = is_bound
            self.calls = 0

        def bind_tools(self, _tools):
            bound = _EmptyBoundThenTextModel(is_bound=True)
            bound.bound = self
            return bound

        async def ainvoke(self, _messages, **_kwargs):
            self.calls += 1
            if self.is_bound:
                return AIMessage(content="", tool_calls=[])
            return AIMessage(content="Recovered response after empty native output.")

    raw_model = _EmptyBoundThenTextModel()
    node = AgentExecutionNode(
        model=raw_model,
        registry=AgentRegistry(agents_dir=agents_dir, skills_dir=skills_dir),
        tool_registry=ToolSpecRegistry(),
    )
    out = await node.execute({
        "current_agent": "metrics-assistant",
        "agent_id": "metrics-assistant",
        "effective_tools": ["workspace-note"],
        "messages": [HumanMessage(content="Summarize my workspace metrics.")],
    })
    assert raw_model.calls == 1
    assert out["output"] == "Recovered response after empty native output."
    assert out["next_step"] == "output_guardrail"
