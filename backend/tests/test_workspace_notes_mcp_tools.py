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

"""End-to-end tests for governed workspace notes MCP/DB CRUD tools and runtime wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.db.base import Base
import yarvelle_core.db.models  # noqa: F401
from yarvelle_core.db.models import Note
from yarvelle_core.db.session import create_db_engine
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.engine.tool_registry import create_default_registry
from yarvelle_core.scope.context import scope_context
from yarvelle_core.tools.builtin_handlers import exec_workspace_note
from yarvelle_core.tools.mcp_db_toolbox import (
    WORKSPACE_NOTE_MCP_TOOLS,
    expand_workspace_note_tools,
    get_db_toolbox,
)
from yarvelle_core.workflows.nodes.agent_execution_node import (
    AgentExecutionNode,
    _parse_fallback_tool_calls,
)
from yarvelle_core.workflows.nodes.main_agent_node import MainAgentNode
from yarvelle_core.workflows.nodes.tool_node import ToolNode


@pytest.fixture
async def isolated_notes_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provides a clean SQLite database wired into db.session and mcp_db_toolbox."""
    from yarvelle_core.config import settings

    db_file = tmp_path / "notes_crud.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setenv("YARVELLE_DATABASE_URL", db_url)

    engine = create_db_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    import yarvelle_core.db.session as db_session_mod
    import yarvelle_core.tools.mcp_db_toolbox as toolbox_mod

    monkeypatch.setattr(db_session_mod, "_engine", engine, raising=False)
    monkeypatch.setattr(db_session_mod, "_session_factory", factory, raising=False)
    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda *a, **k: factory)
    monkeypatch.setattr(toolbox_mod, "get_session_factory", lambda *a, **k: factory)

    try:
        yield factory
    finally:
        await engine.dispose()


def _make_note_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws_notes"
    (ws / "workspace" / "notes").mkdir(parents=True, exist_ok=True)
    (ws / "attachments").mkdir(parents=True, exist_ok=True)
    (ws / "skills").mkdir(parents=True, exist_ok=True)
    (ws / "logs").mkdir(parents=True, exist_ok=True)
    agents_dir = ws / "agents"
    for aid, tools in [
        ("note-assistant", ["workspace-note"]),
        ("reader-only", ["attach-read"]),
        ("bare-agent", []),
    ]:
        adir = agents_dir / aid
        adir.mkdir(parents=True, exist_ok=True)
        tools_yaml = "[]" if not tools else "\n" + "\n".join(f"  - {t}" for t in tools)
        (adir / "persona.md").write_text(f"You are {aid}.\n", encoding="utf-8")
        (adir / "agent.yaml").write_text(
            f"name: {aid}\n"
            f"domain: general\n"
            f"risk_class: wellness\n"
            f"description: Test agent {aid}\n"
            f"tools: {tools_yaml}\n"
            f"persona: persona.md\n",
            encoding="utf-8",
        )
    return ws


class _NativeBoundRunnable:
    """Fake bound runnable returned by _NativeToolChatModel.bind_tools()."""

    def __init__(self, parent: "_NativeToolChatModel", bound_tools: List[Any]) -> None:
        self.parent = parent
        self.bound = parent
        self.bound_tools = bound_tools

    async def ainvoke(self, messages: List[Any]) -> AIMessage:
        self.parent.recorded_bound_tools.append(list(self.bound_tools))
        self.parent.recorded_messages.append(list(messages))
        return self.parent._next_reply(is_bound=True, messages=messages)


class _NativeToolChatModel:
    """Mock model recording bound OpenAI schemas and returning queued AIMessages."""

    def __init__(self, replies: List[AIMessage]) -> None:
        self._replies = list(replies)
        self.recorded_bound_tools: List[List[Any]] = []
        self.recorded_messages: List[List[Any]] = []

    def bind_tools(self, tools: List[Any]) -> _NativeBoundRunnable:
        return _NativeBoundRunnable(self, tools)

    def _next_reply(self, *, is_bound: bool, messages: List[Any]) -> AIMessage:
        return self._replies.pop(0)

    async def ainvoke(self, messages: List[Any]) -> AIMessage:
        self.recorded_messages.append(list(messages))
        return self._next_reply(is_bound=False, messages=messages)


class _UnsupportedToolsBoundRunnable:
    """Raises Ollama-style unsupported-tools error when bound invocation runs."""

    def __init__(self, parent: "_FallbackOnlyChatModel", bound_tools: List[Any]) -> None:
        self.parent = parent
        self.bound = parent
        self.bound_tools = bound_tools

    async def ainvoke(self, messages: List[Any]) -> AIMessage:
        self.parent.recorded_bound_tools.append(list(self.bound_tools))
        raise RuntimeError("model does not support tools (status code: 400)")


class _FallbackOnlyChatModel:
    """Mock model rejecting native bind_tools invocations and replying via unbound ainvoke."""

    def __init__(self, replies: List[str]) -> None:
        self._replies = list(replies)
        self.recorded_bound_tools: List[List[Any]] = []
        self.unbound_messages: List[List[Any]] = []

    def bind_tools(self, tools: List[Any]) -> _UnsupportedToolsBoundRunnable:
        return _UnsupportedToolsBoundRunnable(self, tools)

    async def ainvoke(self, messages: List[Any]) -> AIMessage:
        self.unbound_messages.append(list(messages))
        return AIMessage(content=self._replies.pop(0))


def _scope_for(
    profile_id: str,
    scope: str = "general",
    *,
    declared_reads: tuple[str, ...] = (),
):
    return scope_context(
        scope=scope,
        granted_scopes=(scope,),
        active_scopes=(scope,),
        profile_id=profile_id,
        pack_id="core",
        pack_declared_scopes=(scope, f"{scope}.*"),
        declared_reads=declared_reads,
    )


@pytest.mark.asyncio
async def test_workspace_note_mcp_full_crud_and_legacy_persistence(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Verifies all 6 note CRUD MCP tools plus workspace-note DB delegation."""
    toolbox = get_db_toolbox()
    ws = _make_note_workspace(tmp_path)

    with _scope_for("prof-crud", "general"):
        created = await toolbox.execute(
            "create_workspace_note",
            {
                "title": "Project Kickoff",
                "content": "Initial checklist for Monday.",
                "type": "checklist",
                "tags_json": json.dumps(["planning", "Q4"]),
            },
            profile_id="prof-crud",
            scope="general",
            user_id=None,
        )
        assert created["status"] == "ok"
        assert created["action"] == "created"
        assert created["record"]["slug"] == "project-kickoff"
        assert created["record"]["title"] == "Project Kickoff"
        assert created["record"]["tags"] == ["planning", "Q4"]
        note_id = created["record"]["id"]

        # Read by slug and by note_id
        by_slug = await toolbox.execute(
            "get_workspace_note",
            {"slug": "project-kickoff"},
            profile_id="prof-crud",
            scope="general",
        )
        assert by_slug["status"] == "ok"
        assert by_slug["record"]["id"] == note_id

        by_id = await toolbox.execute(
            "get_workspace_note",
            {"note_id": note_id},
            profile_id="prof-crud",
            scope="general",
        )
        assert by_id["status"] == "ok"
        assert by_id["record"]["content"] == "Initial checklist for Monday."

        # Update preserving omitted title, type, and tags
        updated = await toolbox.execute(
            "update_workspace_note",
            {
                "slug": "project-kickoff",
                "content": "Updated checklist with Tuesday review.",
            },
            profile_id="prof-crud",
            scope="general",
        )
        assert updated["status"] == "ok"
        assert updated["record"]["title"] == "Project Kickoff"
        assert updated["record"]["type"] == "checklist"
        assert updated["record"]["tags"] == ["planning", "Q4"]
        assert "Tuesday review" in updated["record"]["content"]

        # Upsert existing vs new note
        upserted_existing = await toolbox.execute(
            "upsert_workspace_note",
            {
                "slug": "project-kickoff",
                "title": "Project Kickoff v2",
                "content": "Upserted content.",
            },
            profile_id="prof-crud",
            scope="general",
        )
        assert upserted_existing["status"] == "ok"
        assert upserted_existing["action"] == "updated"
        assert upserted_existing["record"]["id"] == note_id
        assert upserted_existing["record"]["tags"] == ["planning", "Q4"]

        upserted_new = await toolbox.execute(
            "upsert_workspace_note",
            {
                "title": "Weekly Log",
                "content": "Completed tasks on Friday.",
                "type": "summary",
                "tags_json": json.dumps(["weekly"]),
            },
            profile_id="prof-crud",
            scope="general",
        )
        assert upserted_new["status"] == "ok"
        assert upserted_new["action"] == "created"

        # List with tag, type, query, and pagination
        listed_tag = await toolbox.execute(
            "list_workspace_notes",
            {"tag": "Q4", "type": "checklist", "query": "Upserted", "limit": 10, "offset": 0},
            profile_id="prof-crud",
            scope="general",
        )
        assert listed_tag["status"] == "ok"
        assert listed_tag["count"] == 1
        assert listed_tag["total"] == 1
        assert listed_tag["records"][0]["id"] == note_id

        listed_page = await toolbox.execute(
            "list_workspace_notes",
            {"limit": 1, "offset": 1},
            profile_id="prof-crud",
            scope="general",
        )
        assert listed_page["status"] == "ok"
        assert listed_page["total"] == 2
        assert listed_page["count"] == 1

        # workspace-note legacy tool also delegates to upsert_workspace_note in DB
        (ws / "backend").mkdir(exist_ok=True)
        legacy_ctx = ToolContext(
            user_id="missing_user_row",
            profile_id="prof-crud",
            run_id="run-legacy",
            autonomy="A1",
            workspace_root=ws,
            skills_dir=ws / "skills",
            effective_tools=("workspace-note",),
        )
        legacy_spec = create_default_registry().get("workspace-note")
        assert legacy_spec is not None
        legacy_res = await execute_tool_call(
            legacy_ctx,
            legacy_spec,
            {"title": "Direct File Note", "content": "Saved to file and DB."},
        )
        assert legacy_res.success is True
        legacy_out = legacy_res.output
        assert legacy_out["db_saved"] is True
        assert legacy_out["note_id"]

        # Delete by slug
        deleted = await toolbox.execute(
            "delete_workspace_note",
            {"slug": "project-kickoff"},
            profile_id="prof-crud",
            scope="general",
        )
        assert deleted["status"] == "ok"
        assert deleted["deleted"] is True

        missing = await toolbox.execute(
            "get_workspace_note",
            {"slug": "project-kickoff"},
            profile_id="prof-crud",
            scope="general",
        )
        assert missing["status"] == "not_found"


@pytest.mark.asyncio
async def test_slug_collision_suffixing_and_cross_scope_profile_isolation(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Verifies unique slug collision suffixing and strict profile/scope isolation."""
    toolbox = get_db_toolbox()
    ws = _make_note_workspace(tmp_path)
    reg = create_default_registry()

    with _scope_for("profile-a", "alpha"):
        c1 = await toolbox.execute(
            "create_workspace_note",
            {"title": "Daily Summary", "content": "First version"},
            profile_id="profile-a",
            scope="alpha",
            user_id=None,
        )
        c2 = await toolbox.execute(
            "create_workspace_note",
            {"title": "Daily Summary", "content": "Second version"},
            profile_id="profile-a",
            scope="alpha",
            user_id=None,
        )
        c3 = await toolbox.execute(
            "create_workspace_note",
            {"title": "Daily Summary", "content": "Third version"},
            profile_id="profile-a",
            scope="alpha",
            user_id=None,
        )
        assert [c1["record"]["slug"], c2["record"]["slug"], c3["record"]["slug"]] == [
            "daily-summary",
            "daily-summary-2",
            "daily-summary-3",
        ]

    # Profile B cannot read/update/delete Profile A's note through execute_tool_call
    ctx_b = ToolContext(
        user_id="user-b",
        profile_id="profile-b",
        run_id="run-iso-b",
        autonomy="A1",
        workspace_root=ws,
        skills_dir=ws / "skills",
        effective_tools=("create_workspace_note", "get_workspace_note", "update_workspace_note", "delete_workspace_note"),
    )
    with _scope_for("profile-b", "alpha"):
        get_spec = reg.get("get_workspace_note")
        upd_spec = reg.get("update_workspace_note")
        del_spec = reg.get("delete_workspace_note")
        assert get_spec is not None and upd_spec is not None and del_spec is not None

        res_get = await execute_tool_call(ctx_b, get_spec, {"slug": "daily-summary"})
        assert res_get.success is True
        assert res_get.output["status"] == "not_found"

        res_upd = await execute_tool_call(ctx_b, upd_spec, {"slug": "daily-summary", "content": "Tamper"})
        assert res_upd.success is True
        assert res_upd.output["status"] == "not_found"

        res_del = await execute_tool_call(ctx_b, del_spec, {"slug": "daily-summary"})
        assert res_del.success is True
        assert res_del.output["status"] == "not_found"

    # Profile A in scope "beta" cannot see Profile A's notes from scope "alpha"
    ctx_a_beta = ToolContext(
        user_id="user-a",
        profile_id="profile-a",
        run_id="run-iso-beta",
        autonomy="A1",
        workspace_root=ws,
        skills_dir=ws / "skills",
        effective_tools=("get_workspace_note", "list_workspace_notes", "update_workspace_note", "delete_workspace_note"),
    )
    with _scope_for("profile-a", "beta"):
        res_list = await execute_tool_call(ctx_a_beta, reg.get("list_workspace_notes"), {})
        assert res_list.success is True
        assert res_list.output["count"] == 0

        res_beta_get = await execute_tool_call(ctx_a_beta, reg.get("get_workspace_note"), {"slug": "daily-summary"})
        assert res_beta_get.output["status"] == "not_found"

    # Original note in profile-a / alpha remains intact
    with _scope_for("profile-a", "alpha"):
        intact = await toolbox.execute(
            "get_workspace_note",
            {"slug": "daily-summary"},
            profile_id="profile-a",
            scope="alpha",
        )
        assert intact["status"] == "ok"
        assert intact["record"]["content"] == "First version"


@pytest.mark.asyncio
async def test_agent_execution_and_tool_node_native_bind_tools_crud(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Verifies AgentExecutionNode serializes ToolSpecs and ToolNode executes CRUD."""
    ws = _make_note_workspace(tmp_path)
    registry = AgentRegistry(ws / "agents", ws / "skills")
    tool_registry = create_default_registry()

    replies = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_create",
                    "name": "create_workspace_note",
                    "args": {"title": "Packing List", "content": "Passport and charger."},
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="Saved your 'Packing List' note."),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_update",
                    "name": "update_workspace_note",
                    "args": {"slug": "packing-list", "content": "Passport, charger, and adapter."},
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="Updated your 'Packing List' note."),
    ]
    model = _NativeToolChatModel(replies)
    exec_node = AgentExecutionNode(model=model, registry=registry, tool_registry=tool_registry)
    tool_node = ToolNode()

    with _scope_for("prof-native", "general"):
        # Create turn
        state1: Dict[str, Any] = {
            "current_agent": "note-assistant",
            "agent_id": "note-assistant",
            "workspace_root": str(ws),
            "skills_dir": str(ws / "skills"),
            "profile_id": "prof-native",
            "user_id": "u-native",
            "messages": [HumanMessage(content="Save a packing list note.")],
            "iteration_count": 0,
        }
        out1 = await exec_node.execute(state1)
        assert out1["next_step"] == "tools"
        bound_names = {
            (t["function"]["name"] if "function" in t else t["name"])
            for t in model.recorded_bound_tools[0]
            if isinstance(t, dict) and ("function" in t or "name" in t)
        }
        assert set(WORKSPACE_NOTE_MCP_TOOLS).issubset(bound_names)
        sys_msg = model.recorded_messages[0][0]
        assert isinstance(sys_msg, SystemMessage)
        assert "WORKSPACE NOTES & PERSISTENT RECORD TOOLS" in str(sys_msg.content)

        tool_out1 = await tool_node.execute({**state1, **out1})
        tool_msg1 = tool_out1["tool_messages"][0]
        assert isinstance(tool_msg1, ToolMessage)
        assert '"status": "ok"' in str(tool_msg1.content)

        # Follow-up model turn after tool
        state1_done = {
            **state1,
            "messages": state1["messages"] + out1["messages"] + tool_out1["messages"],
            "iteration_count": 1,
            "effective_tools": out1["effective_tools"],
        }
        out1_final = await exec_node.execute(state1_done)
        assert out1_final["next_step"] == "output_guardrail"
        assert "Packing List" in out1_final["output"]

        # Update turn
        state2: Dict[str, Any] = {
            **state1_done,
            "messages": state1_done["messages"] + out1_final["messages"] + [HumanMessage(content="Add adapter to packing list.")],
            "iteration_count": 0,
        }
        out2 = await exec_node.execute(state2)
        assert out2["next_step"] == "tools"
        tool_out2 = await tool_node.execute({**state2, **out2})
        assert "adapter" in str(tool_out2["tool_messages"][0].content)

        async with isolated_notes_db() as session:
            rows = (
                await session.execute(select(Note).where(Note.profile_id == "prof-native"))
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].slug == "packing-list"
            assert rows[0].content == "Passport, charger, and adapter."


@pytest.mark.asyncio
async def test_agent_execution_node_fallback_json_tool_calling_for_non_tool_models(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Verifies models raising 'does not support tools' still execute CRUD via JSON fallback."""
    ws = _make_note_workspace(tmp_path)
    registry = AgentRegistry(ws / "agents", ws / "skills")
    tool_registry = create_default_registry()

    model = _FallbackOnlyChatModel(
        replies=[
            '```json\n{"tool_calls": [{"name": "create_workspace_note", "args": {"title": "Fallback Note", "content": "Persisted without native bind_tools."}}]}\n```',
            "I saved your Fallback Note to your workspace.",
        ]
    )
    exec_node = AgentExecutionNode(model=model, registry=registry, tool_registry=tool_registry)
    tool_node = ToolNode()

    with _scope_for("prof-fallback", "general"):
        state: Dict[str, Any] = {
            "current_agent": "note-assistant",
            "agent_id": "note-assistant",
            "workspace_root": str(ws),
            "skills_dir": str(ws / "skills"),
            "profile_id": "prof-fallback",
            "user_id": "u-fallback",
            "messages": [HumanMessage(content="Save a note titled Fallback Note.")],
            "iteration_count": 0,
        }
        out1 = await exec_node.execute(state)
        assert out1["next_step"] == "tools"
        assert len(out1["tool_calls"]) == 1
        assert out1["tool_calls"][0]["name"] == "create_workspace_note"
        assert "TOOL INVOCATION FALLBACK PROTOCOL" in str(model.unbound_messages[0][0].content)

        tool_res = await tool_node.execute({**state, **out1})
        assert '"status": "ok"' in str(tool_res["tool_messages"][0].content)

        out2 = await exec_node.execute(
            {
                **state,
                "messages": state["messages"] + out1["messages"] + tool_res["messages"],
                "iteration_count": 1,
                "effective_tools": out1["effective_tools"],
            }
        )
        assert out2["next_step"] == "output_guardrail"
        assert "TOOL INVOCATION FALLBACK PROTOCOL" in str(model.unbound_messages[1][0].content)
        assert not any(isinstance(m, ToolMessage) for m in model.unbound_messages[1])
        assert isinstance(model.unbound_messages[1][-1], HumanMessage)
        assert "[Tool Execution Result — create_workspace_note]" in str(
            model.unbound_messages[1][-1].content
        )
        assert "fallback-note" in str(model.unbound_messages[1][-1].content)
        assert "saved your Fallback Note" in out2["output"]

        async with isolated_notes_db() as session:
            note = (
                await session.execute(select(Note).where(Note.profile_id == "prof-fallback"))
            ).scalar_one_or_none()
            assert note is not None
            assert note.slug == "fallback-note"
            assert note.content == "Persisted without native bind_tools."


@pytest.mark.asyncio
async def test_main_agent_node_default_tool_resolver_executes_note_tools(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Verifies MainAgentNode builds a governed StructuredTool resolver when none is injected."""
    ws = _make_note_workspace(tmp_path)
    registry = AgentRegistry(ws / "agents", ws / "skills")
    main_node = MainAgentNode(
        model=_NativeToolChatModel([]),
        registry=registry,
        tool_registry=create_default_registry(),
    )

    state: Dict[str, Any] = {
        "workspace_root": str(ws),
        "skills_dir": str(ws / "skills"),
        "profile_id": "prof-main-agent",
        "user_id": "u-main",
        "thread_id": "thread-main-1",
        "autonomy": "A1",
    }
    resolver = main_node._build_turn_tool_resolver(state)
    resolved_tools = resolver("note-assistant", ["workspace-note"])
    tool_by_name = {t.name: t for t in resolved_tools}
    assert set(WORKSPACE_NOTE_MCP_TOOLS).issubset(tool_by_name.keys())

    with _scope_for("prof-main-agent", "general"):
        raw_json = await tool_by_name["create_workspace_note"].ainvoke(
            {"title": "Delegated Note", "content": "Created from main agent resolver."}
        )
    parsed = json.loads(raw_json)
    assert parsed["status"] == "ok"
    assert parsed["record"]["slug"] == "delegated-note"

    with _scope_for("prof-main-agent", "general"):
        async with isolated_notes_db() as session:
            saved = (
                await session.execute(select(Note).where(Note.profile_id == "prof-main-agent"))
            ).scalar_one_or_none()
            assert saved is not None
            assert saved.content == "Created from main agent resolver."


@pytest.mark.asyncio
async def test_allowlist_negative_boundaries_do_not_leak_note_tools(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Agents without workspace-note or note MCP tools do not expand or execute note CRUD."""
    ws = _make_note_workspace(tmp_path)
    registry = AgentRegistry(ws / "agents", ws / "skills")
    tool_registry = create_default_registry()
    exec_node = AgentExecutionNode(model=_NativeToolChatModel([]), registry=registry, tool_registry=tool_registry)
    tool_node = ToolNode()

    assert expand_workspace_note_tools([]) == []
    assert expand_workspace_note_tools(["attach-read"]) == ["attach-read"]

    for agent_id, declared in [("bare-agent", []), ("reader-only", ["attach-read"])]:
        manifest = registry.get(agent_id)
        assert manifest is not None
        eff = exec_node._resolve_effective_tool_names(agent_id, manifest, {})
        assert eff == declared
        prompt = exec_node._resolve_system_prompt(manifest, {}, effective_tools=eff)
        assert "WORKSPACE NOTES & PERSISTENT RECORD TOOLS" not in prompt

        denied = await tool_node.execute(
            {
                "current_agent": agent_id,
                "agent_id": agent_id,
                "workspace_root": str(ws),
                "skills_dir": str(ws / "skills"),
                "profile_id": "prof-neg",
                "effective_tools": eff,
                "tool_calls": [
                    {
                        "id": "call_denied",
                        "name": "create_workspace_note",
                        "args": {"title": "Blocked", "content": "Should fail"},
                    }
                ],
            }
        )
        assert denied["tool_messages"][0].status == "error"
        assert "execution denied: undeclared tool" in str(denied["tool_messages"][0].content)


def test_parse_fallback_tool_calls_accepts_tool_code_fence_flat_args_and_openai_nested() -> None:
    """Fallback parser extracts flat sibling args from ```tool_code fences and OpenAI nested calls."""
    allowed = set(WORKSPACE_NOTE_MCP_TOOLS)

    flat_reply = (
        "```tool_code\n"
        '{\n  "tool": "update_workspace_note",\n'
        '  "identifier": "Quarterly Summary Alpha",\n'
        '  "content": "Updated milestone summary."\n'
        "}\n```"
    )
    parsed_flat = _parse_fallback_tool_calls(flat_reply, allowed)
    assert len(parsed_flat) == 1
    assert parsed_flat[0]["name"] == "update_workspace_note"
    assert parsed_flat[0]["args"] == {
        "identifier": "Quarterly Summary Alpha",
        "content": "Updated milestone summary.",
    }

    nested_reply = json.dumps(
        {
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_workspace_note",
                        "arguments": '{"identifier": "Quarterly Summary Alpha"}',
                    },
                }
            ]
        }
    )
    parsed_nested = _parse_fallback_tool_calls(nested_reply, allowed)
    assert len(parsed_nested) == 1
    assert parsed_nested[0]["name"] == "get_workspace_note"
    assert parsed_nested[0]["args"] == {"identifier": "Quarterly Summary Alpha"}


@pytest.mark.asyncio
async def test_workspace_note_mcp_tools_normalize_llm_aliases_and_case_insensitive_title(
    isolated_notes_db: async_sessionmaker[AsyncSession],
) -> None:
    """MCP note CRUD normalizes LLM parameter aliases and resolves suffixed notes by title."""
    toolbox = get_db_toolbox()
    ctx = ToolContext(
        user_id="u-alias",
        profile_id="prof-alias",
        principal="user",
        run_id="r-alias",
        mode="local",
        autonomy="A1",
    )

    with _scope_for("prof-alias", "general"):
        first = await toolbox.execute_tool(
            "create_workspace_note",
            {"title": "Quarterly Summary Alpha", "content": "First entry."},
            ctx=ctx,
        )
        first_id = first["record"]["id"]

        dup1 = await toolbox.execute_tool(
            "create_workspace_note",
            {"note_title": "Quarterly Summary Item", "note_content": "Copy one.", "slug": "item-slug"},
            ctx=ctx,
        )
        dup2 = await toolbox.execute_tool(
            "create_workspace_note",
            {"note_title": "Quarterly Summary UniqueTitle", "note_content": "Copy two.", "slug": "item-slug"},
            ctx=ctx,
        )
        assert dup1["record"]["slug"] == "item-slug"
        assert dup2["record"]["slug"] == "item-slug-2"
        dup2_id = dup2["record"]["id"]

        fetched_by_id = await toolbox.execute_tool("get_workspace_note", {"id": first_id}, ctx=ctx)
        assert fetched_by_id["found"] is True
        assert fetched_by_id["record"]["title"] == "Quarterly Summary Alpha"

        updated_by_alias = await toolbox.execute_tool(
            "update_workspace_note",
            {
                "note_title": "quarterly summary uniquetitle",
                "note_content": "Updated duplicate content.",
                "tags": ["alpha", "beta"],
            },
            ctx=ctx,
        )
        assert updated_by_alias["status"] == "ok"
        assert updated_by_alias["record"]["id"] == dup2_id
        assert updated_by_alias["record"]["content"] == "Updated duplicate content."
        assert updated_by_alias["record"]["tags"] == ["alpha", "beta"]

        updated_by_title = await toolbox.execute_tool(
            "update_workspace_note",
            {"title": "Quarterly Summary UniqueTitle", "content": "Updated via title key."},
            ctx=ctx,
        )
        assert updated_by_title["status"] == "ok"
        assert updated_by_title["record"]["content"] == "Updated via title key."

        listed = await toolbox.execute_tool(
            "list_workspace_notes",
            {"q": "Updated via title key"},
            ctx=ctx,
        )
        assert listed["count"] == 1
        assert listed["records"][0]["id"] == dup2_id

        deleted = await toolbox.execute_tool("delete_workspace_note", {"id": dup2_id}, ctx=ctx)
        assert deleted["deleted"] is True

        async with isolated_notes_db() as session:
            remaining = (
                await session.execute(select(Note).where(Note.id == dup2_id))
            ).scalar_one_or_none()
            assert remaining is None


@pytest.mark.asyncio
async def test_fallback_non_tool_model_skips_duplicate_same_turn_mutation(
    isolated_notes_db: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Suppresses identical repeat JSON tool calls after success in the same fallback turn."""
    ws = _make_note_workspace(tmp_path)
    registry = AgentRegistry(ws / "agents", ws / "skills")
    tool_registry = create_default_registry()

    duplicate_call = (
        "```tool_code\n"
        '{"tool": "create_workspace_note", "title": "Single Entry Note", '
        '"content": "Created once only."}\n```'
    )
    model = _FallbackOnlyChatModel(
        replies=[
            duplicate_call,
            duplicate_call,
            "Your note titled Single Entry Note has been saved.",
        ]
    )
    exec_node = AgentExecutionNode(model=model, registry=registry, tool_registry=tool_registry)
    tool_node = ToolNode()

    with _scope_for("prof-dedup", "general"):
        state: Dict[str, Any] = {
            "current_agent": "note-assistant",
            "agent_id": "note-assistant",
            "workspace_root": str(ws),
            "skills_dir": str(ws / "skills"),
            "profile_id": "prof-dedup",
            "user_id": "u-dedup",
            "messages": [HumanMessage(content="Save Single Entry Note.")],
            "iteration_count": 0,
        }
        out1 = await exec_node.execute(state)
        assert out1["next_step"] == "tools"
        assert len(out1["tool_calls"]) == 1

        tool_res = await tool_node.execute({**state, **out1})
        assert '"status": "ok"' in str(tool_res["tool_messages"][0].content)

        out2 = await exec_node.execute(
            {
                **state,
                "messages": state["messages"] + out1["messages"] + tool_res["messages"],
                "iteration_count": 1,
                "effective_tools": out1["effective_tools"],
            }
        )
        assert out2["next_step"] == "output_guardrail"
        assert out2["tool_calls"] == []
        assert "saved" in out2["output"].lower()
        assert len(model.unbound_messages) == 3

        async with isolated_notes_db() as session:
            rows = (
                await session.execute(select(Note).where(Note.profile_id == "prof-dedup"))
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].slug == "single-entry-note"
