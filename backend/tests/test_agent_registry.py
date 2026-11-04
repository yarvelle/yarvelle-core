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

"""AgentRegistry tests: file + stored sources, duplicates, unknown ids, subagent specs and hooks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from yarvelle_core.agents import (
    AgentNotFoundError,
    AgentRegistry,
    DbAgentSource,
    DuplicateAgentError,
    FilesystemAgentSource,
    SubagentHookError,
)
from yarvelle_core.agents.subagent_hooks import (
    REQUIRED_SUBAGENT_HOOKS,
    SubagentAuditHook,
    SubagentToolPolicyHook,
    ensure_subagent_hooks,
    missing_subagent_hooks,
)
from yarvelle_core.constants.agents import DEFAULT_ROUTING_FALLBACK_AGENT
from yarvelle_core.tools.delegation_tools import ListAgentsTool


def _write_agent(root: Path, agent_id: str, **fields: Any) -> Path:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    data: Dict[str, Any] = {
        "id": agent_id,
        "title": fields.pop("title", agent_id.replace("-", " ").title()),
        "description": fields.pop("description", f"{agent_id} helper"),
        "persona": "persona.md",
        "tools": fields.pop("tools", []),
        "skills": [],
    }
    data.update(fields)
    import yaml

    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (agent_dir / "persona.md").write_text(f"# {agent_id}\n\nYou are the {agent_id} agent.\n", encoding="utf-8")
    return agent_dir


@pytest.fixture()
def workspace(tmp_path: Path) -> Dict[str, Path]:
    agents = tmp_path / "agents"
    skills = tmp_path / "skills"
    skills.mkdir()
    _write_agent(agents, "budget-planner", description="Plans monthly budgets and savings", tags=["money", "budget"])
    _write_agent(agents, "trip-organizer", description="Organizes travel itineraries", tools=["attach-read"])
    _write_agent(agents / "_system", "orchestrator", can_delegate=True)
    _write_agent(agents / "_system", "doc-reader", description="Reads uploaded documents", tools=["attach-read"])
    (agents / "broken-agent").mkdir()
    (agents / "broken-agent" / "agent.yaml").write_text("id: [not, a, slug\n", encoding="utf-8")
    return {"agents": agents, "skills": skills, "root": tmp_path}


def _db_row(agent_id: str, **overrides: Any) -> SimpleNamespace:
    row = dict(
        id=agent_id,
        type="user",
        title=agent_id.replace("-", " ").title(),
        description=f"Stored {agent_id}",
        persona="You are a stored agent.",
        model="ollama:llama3.2",
        skills_json="[]",
        tools_json=json.dumps(["workspace-note"]),
        starters_json="[]",
        domain="general",
        category="general",
        risk_class="admin",
        tags_json=json.dumps(["custom"]),
        care_stages_json="[]",
        target_audience_json="[]",
        forbidden_json="[]",
        icon="Bot",
        maturity="stable",
        can_delegate=False,
        max_iterations=3,
        hidden=False,
    )
    row.update(overrides)
    return SimpleNamespace(**row)


# ---------------------------------------------------------------- sources


def test_file_agents_load_with_system_hidden_and_broken_rejected(workspace):
    reg = AgentRegistry(workspace["agents"], workspace["skills"])
    assert reg.list_agent_ids() == ["budget-planner", "doc-reader", "orchestrator", "trip-organizer"]
    assert reg.resolve("doc-reader").hidden is True
    assert reg.source_of("budget-planner") == "file"
    assert [r.agent_id for r in reg.rejected] == ["broken-agent"]
    assert reg.get_effective_tools("trip-organizer") == ["attach-read"]


def test_db_agents_join_the_same_catalog(workspace):
    db = DbAgentSource([_db_row("custom-coach")], skills_dir=workspace["skills"])
    reg = AgentRegistry(workspace["agents"], workspace["skills"], db_source=db)
    assert "custom-coach" in reg
    assert reg.source_of("custom-coach") == "db"
    manifest = reg.resolve("custom-coach")
    assert manifest.title == "Custom Coach"
    assert manifest.tags == ["custom"]
    assert reg.get_effective_tools("custom-coach") == ["workspace-note"]


def test_set_db_rows_reloads_and_bumps_version(workspace):
    reg = AgentRegistry(workspace["agents"], workspace["skills"])
    v0 = reg.version
    assert "late-agent" not in reg
    reg.set_db_rows([_db_row("late-agent")])
    assert "late-agent" in reg and reg.version == v0 + 1
    reg.set_db_rows([])
    assert "late-agent" not in reg


def test_db_source_skips_seeded_bundled_and_system_rows(workspace):
    rows = [_db_row("seeded-copy", type="bundled"), _db_row("sys-copy", type="system"), _db_row("mine")]
    reg = AgentRegistry(workspace["agents"], workspace["skills"], db_source=DbAgentSource(rows))
    assert "mine" in reg
    assert "seeded-copy" not in reg and "sys-copy" not in reg


def test_invalid_db_rows_are_rejected_not_defaulted(workspace):
    rows = [
        _db_row("bad-tools", tools_json=json.dumps(["not-a-real-tool"])),
        _db_row("Bad Id!"),
        _db_row("needs-skill", skills_json=json.dumps(["missing-skill"])),
    ]
    reg = AgentRegistry(workspace["agents"], workspace["skills"], db_source=DbAgentSource(rows, workspace["skills"]))
    rejected = {r.agent_id: r for r in reg.rejected if r.source == "db"}
    assert set(rejected) == {"bad-tools", "Bad Id!", "needs-skill"}
    assert "missing-skill" in rejected["needs-skill"].reason
    for aid in rejected:
        assert aid not in reg


def test_db_persona_json_object_is_parsed(workspace):
    persona = json.dumps({"role": "Stored role line", "instructions": "Do the thing."})
    reg = AgentRegistry(workspace["agents"], db_source=DbAgentSource([_db_row("obj-persona", persona=persona)]))
    spec = reg.get_subagent("obj-persona")
    assert spec["system_prompt"] == "Stored role line\n\nDo the thing."


# ------------------------------------------------------------- duplicates


def test_file_vs_db_clash_keeps_file_and_records_conflict(workspace):
    db = DbAgentSource([_db_row("budget-planner", description="Shadow copy")])
    reg = AgentRegistry(workspace["agents"], workspace["skills"], db_source=db)
    assert reg.source_of("budget-planner") == "file"
    assert reg.resolve("budget-planner").description == "Plans monthly budgets and savings"
    assert len(reg.conflicts) == 1
    c = reg.conflicts[0]
    assert (c.agent_id, c.kept_source, c.ignored_source) == ("budget-planner", "file", "db")


def test_duplicate_file_ids_across_sources_fail_loudly(workspace):
    other = workspace["root"] / "pack-agents"
    _write_agent(other, "budget-planner")
    with pytest.raises(DuplicateAgentError) as exc:
        AgentRegistry(workspace["agents"], workspace["skills"], sources=[FilesystemAgentSource(other)])
    assert exc.value.agent_id == "budget-planner"
    assert len(exc.value.origins) == 2


def test_duplicate_db_rows_fail_loudly(workspace):
    with pytest.raises(DuplicateAgentError):
        AgentRegistry(workspace["agents"], db_source=DbAgentSource([_db_row("twin"), _db_row("twin")]))


def test_duplicate_detection_is_deterministic(workspace):
    db = DbAgentSource([_db_row("trip-organizer")])
    first = AgentRegistry(workspace["agents"], db_source=db)
    second = AgentRegistry(workspace["agents"], db_source=db)
    assert first.conflicts == second.conflicts
    assert first.source_of("trip-organizer") == second.source_of("trip-organizer") == "file"


# ------------------------------------------------------------- unknown ids


@pytest.mark.parametrize("bad_id", ["no-such-agent", "", "../etc", "_template", DEFAULT_ROUTING_FALLBACK_AGENT])
def test_unknown_ids_raise_without_fallback(workspace, bad_id):
    reg = AgentRegistry(workspace["agents"], workspace["skills"])
    assert reg.get(bad_id) is None
    with pytest.raises(AgentNotFoundError) as exc:
        reg.resolve(bad_id)
    assert "budget-planner" in exc.value.available
    with pytest.raises(AgentNotFoundError):
        reg[bad_id]
    with pytest.raises(AgentNotFoundError):
        reg.get_subagent(bad_id)
    with pytest.raises(AgentNotFoundError):
        reg.source_of(bad_id)


def test_agent_not_found_is_a_key_error_with_clear_message(workspace):
    reg = AgentRegistry(workspace["agents"])
    with pytest.raises(KeyError) as exc:
        reg["ghost"]
    assert "Unknown agent id 'ghost'" in str(exc.value)


def test_registry_does_not_load_agents_outside_its_sources(workspace, tmp_path, monkeypatch):
    stray = tmp_path / "elsewhere"
    _write_agent(stray, "stray-agent")
    from yarvelle_core.config import settings

    monkeypatch.setattr(type(settings), "get_agents_dir", lambda self: stray)
    reg = AgentRegistry(workspace["agents"])
    assert reg.get("stray-agent") is None


def test_missing_agents_dir_gives_empty_catalog(tmp_path):
    reg = AgentRegistry(tmp_path / "nope")
    assert len(reg) == 0
    with pytest.raises(AgentNotFoundError):
        reg.resolve("anything")


# ------------------------------------------------------------ subagent spec


def test_subagent_spec_shape(workspace):
    reg = AgentRegistry(workspace["agents"], workspace["skills"])
    spec = reg.get_subagent("trip-organizer")
    assert set(spec) == {"name", "description", "system_prompt", "tools", "middleware"}
    assert spec["name"] == "trip-organizer"
    assert spec["description"] == "Organizes travel itineraries"
    assert "You are the trip-organizer agent." in spec["system_prompt"]
    assert spec["tools"] == ["attach-read"]


def test_subagent_spec_includes_model_only_when_declared(workspace):
    reg = AgentRegistry(workspace["agents"], db_source=DbAgentSource([_db_row("with-model", model="llama3.2")]))
    assert reg.get_subagent("with-model")["model"] == "ollama:llama3.2"
    assert "model" not in reg.get_subagent("budget-planner")


def test_subagent_tools_resolve_to_definitions(workspace):
    reg = AgentRegistry(workspace["agents"])
    tools = reg.get_subagent("trip-organizer", resolve_tools=True)["tools"]
    assert [t["name"] for t in tools] == ["attach-read"]


def test_tool_resolver_overrides_tool_payload(workspace):
    seen: List[Any] = []

    def resolver(manifest, names):
        seen.append((manifest.id, list(names)))
        return [f"tool:{n}" for n in names]

    reg = AgentRegistry(workspace["agents"], tool_resolver=resolver)
    assert reg.get_subagent("trip-organizer")["tools"] == ["tool:attach-read"]
    assert seen == [("trip-organizer", ["attach-read"])]


def test_list_subagents_covers_visible_non_delegating_agents(workspace):
    reg = AgentRegistry(workspace["agents"], db_source=DbAgentSource([_db_row("custom-coach")]))
    names = [s["name"] for s in reg.list_subagents()]
    assert names == ["budget-planner", "custom-coach", "trip-organizer"]


def test_hidden_agent_spec_available_by_explicit_id(workspace):
    reg = AgentRegistry(workspace["agents"])
    assert reg.get_subagent("doc-reader")["name"] == "doc-reader"


def test_subagent_specs_compile_into_a_deep_agent(workspace):
    from deepagents import create_deep_agent
    from langchain_core.tools import tool

    try:
        from tests.fixtures.fake_model import MockChatModel
    except ImportError:  # pragma: no cover - when tests/ is the rootdir
        from fixtures.fake_model import MockChatModel

    @tool("attach-read")
    def attach_read(path: str) -> str:
        """Read an attachment."""
        return path

    reg = AgentRegistry(workspace["agents"], tool_resolver=lambda m, names: [attach_read] if names else [])
    agent = create_deep_agent(model=MockChatModel(), subagents=reg.list_subagents())
    assert agent is not None


# -------------------------------------------------------- hook enforcement


def test_every_produced_subagent_spec_has_policy_and_audit_hooks(workspace):
    """Fails if any spec the registry hands out lacks a required hook (ADR-0005 amendment)."""
    db = DbAgentSource([_db_row("custom-coach")])
    reg = AgentRegistry(workspace["agents"], workspace["skills"], db_source=db)
    specs = reg.list_subagents() + [reg.get_subagent(aid) for aid in reg.list_agent_ids()]
    assert specs
    for spec in specs:
        assert missing_subagent_hooks(spec) == [], spec["name"]
        kinds = [type(m) for m in spec["middleware"]]
        for hook in REQUIRED_SUBAGENT_HOOKS:
            assert kinds.count(hook) == 1, (spec["name"], hook.__name__)
        for m in spec["middleware"]:
            if isinstance(m, REQUIRED_SUBAGENT_HOOKS):
                assert m.agent_id == spec["name"]


def test_hook_check_rejects_specs_without_hooks():
    bare = {"name": "x", "description": "d", "system_prompt": "", "tools": []}
    assert missing_subagent_hooks(bare) == ["SubagentToolPolicyHook", "SubagentAuditHook"]
    with pytest.raises(SubagentHookError):
        ensure_subagent_hooks(bare)
    wrong_owner = dict(bare, middleware=[SubagentToolPolicyHook("y"), SubagentAuditHook("y")])
    assert missing_subagent_hooks(wrong_owner) == ["SubagentToolPolicyHook", "SubagentAuditHook"]
    only_policy = dict(bare, middleware=[SubagentToolPolicyHook("x")])
    assert missing_subagent_hooks(only_policy) == ["SubagentAuditHook"]


def test_middleware_factory_extras_cannot_replace_required_hooks(workspace):
    sentinel = object()
    reg = AgentRegistry(workspace["agents"], middleware_factory=lambda m: [sentinel])
    mw = reg.get_subagent("budget-planner")["middleware"]
    assert isinstance(mw[0], SubagentToolPolicyHook)
    assert isinstance(mw[1], SubagentAuditHook)
    assert mw[2] is sentinel


def test_registry_refuses_to_hand_out_spec_if_hook_construction_breaks(workspace, monkeypatch):
    import yarvelle_core.agents.registry as registry_mod

    monkeypatch.setattr(registry_mod, "required_subagent_middleware", lambda agent_id: [])
    reg = AgentRegistry(workspace["agents"])
    with pytest.raises(SubagentHookError):
        reg.get_subagent("budget-planner")


def test_hooks_have_stable_names():
    assert SubagentToolPolicyHook("a").name == "yarvelle_tool_policy"
    assert SubagentAuditHook("a").name == "yarvelle_audit"


# ------------------------------------------------------------- list_agents


def test_list_agents_tool_searches_catalog(workspace):
    reg = AgentRegistry(workspace["agents"], db_source=DbAgentSource([_db_row("custom-coach")]))
    tool = ListAgentsTool(registry=reg)
    everything = tool.invoke({})
    for aid in ("budget-planner", "custom-coach", "trip-organizer"):
        assert f"**{aid}**" in everything
    assert "orchestrator" not in everything and "doc-reader" not in everything

    hit = tool.invoke({"query": "travel itineraries"})
    assert "**trip-organizer**" in hit and "budget-planner" not in hit

    assert "No agents match" in tool.invoke({"query": "zzz-nothing"})
    assert tool.invoke({"query": "", "limit": 1}).count("- **") == 1


def test_search_orders_by_match_count_then_id(workspace):
    reg = AgentRegistry(workspace["agents"])
    ids = [a.id for a in reg.search("budget money travel")]
    assert ids == ["budget-planner", "trip-organizer"]


@pytest.mark.asyncio
async def test_list_agents_tool_spec_passes_query(workspace, monkeypatch):
    from yarvelle_core.agents import registry as registry_mod
    from yarvelle_core.engine.tool_registry import create_default_registry

    reg = AgentRegistry(workspace["agents"])
    monkeypatch.setattr(registry_mod, "_registry_instance", reg)
    monkeypatch.setattr(registry_mod, "get_agent_registry", lambda *a, **k: reg)
    spec = create_default_registry().get("list_agents")
    assert set(spec.parameters["properties"]) == {"query", "limit"}
    out = await spec.executor({"query": "budgets"}, None)
    assert "**budget-planner**" in out and "trip-organizer" not in out


# ------------------------------------------------- execution node fallbacks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"messages": [{"role": "user", "content": "hi"}]},
        {"current_agent": "no-such-agent", "messages": [{"role": "user", "content": "hi"}]},
    ],
)
async def test_execution_node_never_substitutes_a_default_agent(workspace, state):
    from yarvelle_core.workflows.nodes.agent_execution_node import AgentExecutionNode

    try:
        from tests.fixtures.fake_model import MockChatModel
    except ImportError:  # pragma: no cover
        from fixtures.fake_model import MockChatModel

    model = MockChatModel()
    node = AgentExecutionNode(registry=AgentRegistry(workspace["agents"]), model=model)
    out = await node.execute(dict(state))
    assert out["next_step"] == "error"
    assert "agent" in out["error"].lower()
    assert model.call_count == 0
