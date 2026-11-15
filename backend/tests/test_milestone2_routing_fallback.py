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

"""Unit and behavioral tests for Milestone 2 in Yarvelle Core.

Tests cover:
1. Conversational follow-up detection and routing affinity on Turn 2+.
2. Markdown bold/italic syntax preservation during reference doc preamble stripping.
3. Unsupported tools graceful fallback in MainAgentNode / HybridRouter (e.g. MedGemma).
4. State persistence of last_active_agent across turn boundaries.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from yarvelle_core.schemas.manifest import AgentManifest
from yarvelle_core.engine.orchestration.runtime import HybridRouter, TurnOutcome
from yarvelle_core.engine.service import strip_reference_doc_preamble
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteSource
from yarvelle_core.workflows.nodes.orchestrator_node import (
    OrchestratorNode,
    is_conversational_follow_up,
)
from yarvelle_core.workflows.state import turn_end_values


# ============================================================================
# 1. Conversational Follow-Up Detection Tests
# ============================================================================

def test_conversational_follow_up_detection():
    """Verifies conversational follow-up classifier correctly identifies follow-up queries."""
    # Positive examples: short conversational inquiries
    assert is_conversational_follow_up("Why is that?") is True
    assert is_conversational_follow_up("Tell me more about it") is True
    assert is_conversational_follow_up("Can you explain that in more detail?") is True
    assert is_conversational_follow_up("What should I do?") is True
    assert is_conversational_follow_up("Why?") is True
    assert is_conversational_follow_up("How come?") is True
    assert is_conversational_follow_up("Thanks") is True
    assert is_conversational_follow_up("Got it, thank you") is True
    assert is_conversational_follow_up("What does that mean?") is True
    assert is_conversational_follow_up("Could you elaborate?") is True
    assert is_conversational_follow_up("Go on") is True
    assert is_conversational_follow_up("Please explain") is True

    # Negative examples: long domain-specific queries or non-follow-ups
    assert is_conversational_follow_up("") is False
    assert (
        is_conversational_follow_up(
            "Prepare a complete ledger audit report for quarter three compliance"
        )
        is False
    )
    assert (
        is_conversational_follow_up(
            "Inspect the database schema and migrate records to the newly configured tenant table partition"
        )
        is False
    )


# ============================================================================
# 2. Markdown Syntax Preservation in Reference Doc Preamble Stripping
# ============================================================================

def test_strip_reference_doc_preamble_preserves_bold_markdown():
    """Verifies preamble removal preserves **bold** and *italic* markdown syntax."""
    # Opening bold text after preamble
    input_text = "Based on the provided reference document, **Summary:** Here is the information."
    expected = "**Summary:** Here is the information."
    assert strip_reference_doc_preamble(input_text) == expected

    # Bold preamble followed by bold heading
    input_text_2 = "**Based on the provided reference guide:** **Key Recommendations:** Follow these steps."
    expected_2 = "**Key Recommendations:** Follow these steps."
    assert strip_reference_doc_preamble(input_text_2) == expected_2

    # Colon directly on reference doc
    input_text_3 = "According to the reference checklist: **Item 1:** Verified."
    expected_3 = "**Item 1:** Verified."
    assert strip_reference_doc_preamble(input_text_3) == expected_3

    # Italic syntax
    input_text_4 = "From the reference material, *Note:* Please review the details."
    expected_4 = "*Note:* Please review the details."
    assert strip_reference_doc_preamble(input_text_4) == expected_4

    # Plain text without markdown: strips preamble and capitalizes first letter
    input_text_5 = "Based on the provided reference guide, here are the required actions."
    expected_5 = "Here are the required actions."
    assert strip_reference_doc_preamble(input_text_5) == expected_5

    # Text without preamble: remains completely untouched
    input_text_6 = "**Summary:** Standalone document without preamble."
    assert strip_reference_doc_preamble(input_text_6) == input_text_6


# ============================================================================
# 3. Conversational Routing Affinity on Turn 2+
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_conversational_routing_affinity():
    """Verifies Turn 2+ follow-up queries route to last_active_agent when catalog matches are 0."""
    # Mock registry with a specialist agent and a default agent
    specialist_manifest = AgentManifest(
        id="finance-specialist",
        title="Finance Specialist",
        description="Specialist handling financial ledger operations.",
        persona="Specialist handling financial ledger operations.",
        domain="finance",
        category="finance.ledger",
    )
    default_manifest = AgentManifest(
        id="general-steward",
        title="General Steward",
        description="Default general steward.",
        persona="Default general steward.",
        domain="general",
        category="general.support",
    )

    registry = MagicMock()
    registry.get.side_effect = lambda aid: {
        "finance-specialist": specialist_manifest,
        "general-steward": default_manifest,
    }.get(aid)
    registry._skills_dir = None

    # Mock catalog that returns 0 candidates for conversational follow-up
    catalog = MagicMock()
    catalog.search_agents = AsyncMock(return_value=[])

    # Model mock that returns empty or failing Tier-1
    mock_model = MagicMock()
    mock_model.with_structured_output.side_effect = Exception("No structured output")
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content="{}"))

    orchestrator = OrchestratorNode(
        model=mock_model,
        registry=registry,
        default_agent="general-steward",
        catalog=catalog,
        main_agent_enabled=False,
    )

    # State from Turn 1 checkpoint: last_active_agent is finance-specialist
    state: Dict[str, Any] = {
        "prompt": "Why is that?",
        "messages": [
            HumanMessage(content="What is my account balance?"),
            AIMessage(content="Your balance is positive."),
            HumanMessage(content="Why is that?"),
        ],
        "last_active_agent": "finance-specialist",
        "current_agent": None,
        "explicit_agent": None,
    }

    result = await orchestrator.execute(state)

    # Verify conversational affinity maintained routing to finance-specialist
    assert result["current_agent"] == "finance-specialist"
    assert result["agent_id"] == "finance-specialist"
    assert "Conversational affinity maintained" in result["orchestrator_reasoning"]
    assert result["route_decision"]["source"] == RouteSource.MODEL_CLASSIFIED.value


@pytest.mark.asyncio
async def test_orchestrator_fallback_to_default_when_no_affinity():
    """Verifies routing falls back to default agent when no last_active_agent exists."""
    default_manifest = AgentManifest(
        id="general-steward",
        title="General Steward",
        description="Default general steward.",
        persona="Default general steward.",
        domain="general",
        category="general.support",
    )
    registry = MagicMock()
    registry.get.side_effect = lambda aid: {"general-steward": default_manifest}.get(aid)
    registry._skills_dir = None

    catalog = MagicMock()
    catalog.search_agents = AsyncMock(return_value=[])

    mock_model = MagicMock()
    mock_model.with_structured_output.side_effect = Exception("No structured output")
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content="{}"))

    orchestrator = OrchestratorNode(
        model=mock_model,
        registry=registry,
        default_agent="general-steward",
        catalog=catalog,
        main_agent_enabled=False,
    )

    # State without last_active_agent
    state: Dict[str, Any] = {
        "prompt": "Why is that?",
        "messages": [HumanMessage(content="Why is that?")],
        "last_active_agent": None,
        "current_agent": None,
    }

    result = await orchestrator.execute(state)

    # Without last_active_agent, routes to default agent
    assert result["current_agent"] == "general-steward"
    assert result["route_decision"]["source"] == RouteSource.DEFAULT_AGENT.value


# ============================================================================
# 4. Turn End Values & State Retention
# ============================================================================

def test_turn_end_values_preserves_active_agent():
    """Verifies turn_end_values records the active agent in last_active_agent."""
    # When active agent completed the turn
    state_turn_1: Dict[str, Any] = {
        "current_agent": "task-specialist",
        "explicit_agent": "task-specialist",
        "execution_plan": {"target_agents": ["task-specialist"]},
    }
    end_vals = turn_end_values(state_turn_1)
    assert end_vals["last_active_agent"] == "task-specialist"
    assert end_vals["explicit_agent"] is None
    assert end_vals["execution_plan"] is None

    # When turn ended without active agent but already had last_active_agent
    state_refused: Dict[str, Any] = {
        "current_agent": None,
        "last_active_agent": "task-specialist",
    }
    end_vals_refused = turn_end_values(state_refused)
    assert end_vals_refused["last_active_agent"] == "task-specialist"

    # Backward compatibility: no args
    end_vals_bare = turn_end_values()
    assert end_vals_bare == {"explicit_agent": None, "execution_plan": None}


# ============================================================================
# 5. Unsupported Tools Graceful Fallback in HybridRouter (MedGemma)
# ============================================================================

@pytest.mark.asyncio
async def test_hybrid_router_unsupported_tools_fallback():
    """Verifies HybridRouter gracefully falls back when a model does not support tools."""
    # Mock model that raises Ollama-style unsupported tools exception
    class UnsupportedToolsModel:
        def bind_tools(self, *args, **kwargs):
            return self

        async def ainvoke(self, *args, **kwargs):
            raise Exception("ResponseError: registry.ollama.ai/library/medgemma:latest does not support tools (status code: 400)")

    mock_model = UnsupportedToolsModel()

    default_manifest = AgentManifest(
        id="general-steward",
        title="General Steward",
        description="Default general steward.",
        persona="Default general steward.",
        domain="general",
        category="general.support",
    )
    registry = MagicMock()
    registry.get.side_effect = lambda aid: {"general-steward": default_manifest}.get(aid)
    registry.get_delegatable_agents.return_value = [default_manifest]
    registry.list_subagents.return_value = [{"name": "general-steward", "tools": []}]

    spec = PackOrchestrationSpec(default_agent="general-steward")
    router = HybridRouter(
        registry=registry,
        model=mock_model,
        spec=spec,
        default_agent="general-steward",
    )

    state: Dict[str, Any] = {
        "messages": [HumanMessage(content="Hello, help me with a task.")],
        "turn_id": "turn_123",
        "thread_id": "thread_456",
    }

    outcome = await router.run(state, turn_id="turn_123", thread_id="thread_456")

    # Verify graceful degradation
    assert isinstance(outcome, TurnOutcome)
    assert outcome.decision.source == RouteSource.DEFAULT_AGENT
    assert outcome.decision.agent_id == "general-steward"
    assert outcome.decision.fallback_reason == "main_agent_failed"
    assert any(n.code == "main_agent_failed" for n in outcome.notices)


@pytest.mark.asyncio
async def test_service_multiturn_last_active_agent_restored(tmp_path) -> None:
    """Verifies AgentExecutionService restores last_active_agent from checkpoint."""
    from unittest.mock import patch
    import yaml
    from yarvelle_core.engine.service import AgentExecutionService

    agent_dir = tmp_path / "agents" / "finance-specialist"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "id": "finance-specialist",
        "title": "Finance Specialist",
        "description": "Finance Specialist description",
        "persona": "persona.md",
        "tools": [],
        "skills": [],
    }
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(manifest_data), encoding="utf-8")
    (agent_dir / "persona.md").write_text("You are a finance specialist.\n", encoding="utf-8")

    class InMemoryCP:
        def __init__(self, channels: Dict[str, Any]):
            self.channels = channels
            self.tuple_obj = MagicMock()
            self.tuple_obj.checkpoint = {"channel_values": self.channels}

        async def aget_tuple(self, config: Dict[str, Any]) -> Any:
            return self.tuple_obj

    turn1_channels = {
        "messages": [HumanMessage(content="Turn 1"), AIMessage(content="Answer 1")],
        "last_active_agent": "finance-specialist",
    }
    cp = InMemoryCP(turn1_channels)
    service = AgentExecutionService(workspace_root=tmp_path, checkpointer=cp)

    captured_inputs: List[Dict[str, Any]] = []

    class MockGraph:
        async def astream_events(self, initial_input: Dict[str, Any], config: Any, version: str) -> Any:
            captured_inputs.append(initial_input)
            if False:
                yield {}

    with patch.object(service, "_build_execution_graph", return_value=MockGraph()):
        async for _ in service.execute_turn(
            agent_id="finance-specialist",
            prompt="Why is that?",
            thread_id="th-affinity-1",
            user_id="user-1",
            profile_id="profile-1",
        ):
            pass

    assert len(captured_inputs) == 1
    inp = captured_inputs[0]
    assert inp["last_active_agent"] == "finance-specialist"


# ============================================================================
# 6. Skill Docs Real Resolution & Tool Output Preamble Stripping
# ============================================================================


def test_strip_reference_doc_preamble_strips_tool_output_phrases():
    """Verifies preamble removal strips 'Based on the tool output...' while keeping bold markdown."""
    assert (
        strip_reference_doc_preamble("Based on the tool output, **Summary:** Key items.")
        == "**Summary:** Key items."
    )
    assert (
        strip_reference_doc_preamble("Based on the tool output, here are next steps.")
        == "Here are next steps."
    )
    assert (
        strip_reference_doc_preamble("According to the tool result: **Overview:** Details follow.")
        == "**Overview:** Details follow."
    )


@pytest.mark.asyncio
async def test_execute_skill_docs_returns_available_docs_on_missing_and_resolves_real_files(tmp_path):
    """Verifies execute_skill_docs never synthesizes placeholder docs and resolves real filenames."""
    from types import SimpleNamespace
    from yarvelle_core.tools.skill_docs import execute_skill_docs

    skill_dir = tmp_path / "skills" / "project-planner"
    ref_dir = skill_dir / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: project-planner\ndescription: Project planning skill\n---\n\n# Project Planner\n\nFollow structured planning steps.\n",
        encoding="utf-8",
    )
    (ref_dir / "action_items.md").write_text(
        "# Action Items\n\n- Confirm milestones.\n",
        encoding="utf-8",
    )

    agent = AgentManifest(
        id="planning-coordinator",
        title="Planning Coordinator",
        description="Coordinates planning tasks.",
        persona="You are a planning coordinator.",
        skills=["project-planner"],
        tools=["skill-docs"],
    )
    ctx = SimpleNamespace(
        agent=agent,
        workspace_root=tmp_path,
        skills_dir=tmp_path / "skills",
        state={},
    )

    # 1. Missing doc returns error listing real available documents (no synthesized placeholder)
    missing_res = await execute_skill_docs(
        {"skill_id": "project-planner", "doc": "nonexistent_guide.md"},
        ctx,
    )
    assert missing_res.success is False
    assert missing_res.output is None
    assert "not found" in (missing_res.error or "").lower()
    assert "Available documents: action_items.md, SKILL.md" in (missing_res.error or "")

    # 2. Hyphenated alias resolves real underscore reference file on disk
    alias_res = await execute_skill_docs(
        {"skill_id": "project-planner", "doc": "action-items.md"},
        ctx,
    )
    assert alias_res.success is True
    assert alias_res.output is not None
    assert alias_res.output["doc"] == "action_items.md"
    assert "Confirm milestones." in alias_res.output["content"]

    # 3. Direct SKILL.md request reads the skill manifest
    skill_md_res = await execute_skill_docs(
        {"skill_id": "project-planner", "doc": "SKILL.md"},
        ctx,
    )
    assert skill_md_res.success is True
    assert skill_md_res.output is not None
    assert skill_md_res.output["doc"] == "SKILL.md"
    assert "Follow structured planning steps." in skill_md_res.output["content"]


def test_agent_execution_node_lists_available_reference_docs(tmp_path):
    """Verifies AgentExecutionNode surfaces available reference filenames in declared_skills."""
    from yarvelle_core.schemas.manifest import SkillManifest
    from yarvelle_core.workflows.nodes.agent_execution_node import AgentExecutionNode

    skill = SkillManifest(
        id="project-planner",
        name="Project Planner",
        description="Structured milestone planning.",
        references=["action_items.md", "milestone_checklist.md"],
    )
    agent = AgentManifest(
        id="planning-coordinator",
        title="Planning Coordinator",
        description="Coordinates planning tasks.",
        persona="You are a planning coordinator.",
        skills=["project-planner"],
        tools=["skill-docs"],
    )

    registry = MagicMock()
    registry.get_loaded_skills.return_value = [skill]
    registry.get_skill.return_value = skill
    registry._skills_dir = None

    node = AgentExecutionNode(registry=registry)
    rendered = node._resolve_system_prompt(agent, {"current_agent": "planning-coordinator"})
    assert "Available reference docs: action_items.md, milestone_checklist.md" in rendered


@pytest.mark.asyncio
async def test_reflection_node_emits_remove_message_for_rejected_turn_ai_draft():
    """Verifies ReflectionNode removes current-turn non-tool AI drafts while preserving prior turns."""
    from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
    from yarvelle_core.workflows.nodes.reflection_node import ReflectionNode

    node = ReflectionNode(max_reflections=2)

    # Without messages key, output omits 'messages'
    no_msg_out = await node.execute({"reflection_count": 0, "max_reflections": 2, "output": "Attempt 1"})
    assert "messages" not in no_msg_out
    assert no_msg_out["next_step"] == "agent"

    # With prior turn + current turn rejected AI draft, only current turn AI draft gets RemoveMessage
    msgs = [
        HumanMessage(content="Turn 1 user", id="h1"),
        AIMessage(content="Turn 1 approved answer", id="a1"),
        HumanMessage(content="Turn 2 user", id="h2"),
        AIMessage(content="Turn 2 rejected draft", id="a2_bad"),
    ]
    out = await node.execute(
        {
            "reflection_count": 0,
            "max_reflections": 2,
            "output": "Turn 2 rejected draft",
            "refusal_reason": "forbidden_intent:policy_prohibited",
            "messages": msgs,
        }
    )
    assert out["next_step"] == "agent"
    assert out["reflection_count"] == 1
    assert "assistant role" in out["critique"]
    assert "messages" in out
    assert len(out["messages"]) == 1
    assert isinstance(out["messages"][0], RemoveMessage)
    assert out["messages"][0].id == "a2_bad"


@pytest.mark.asyncio
async def test_agent_execution_node_strips_rejected_ai_message_and_injects_critique_on_reflection():
    """Verifies reflection retry removes trailing AI drafts and surfaces critique in the system prompt."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from yarvelle_core.workflows.nodes.agent_execution_node import AgentExecutionNode

    captured = {}

    class CapturingModel:
        async def ainvoke(self, lc_messages):
            captured["messages"] = lc_messages
            return AIMessage(content="Regarding what you shared, here is your preparation checklist.")

    agent = AgentManifest(
        id="planning-coordinator",
        title="Planning Coordinator",
        description="Coordinates planning tasks.",
        persona="You are a planning coordinator.",
        skills=[],
        tools=[],
    )
    registry = MagicMock()
    registry.get.return_value = agent
    registry.get_loaded_skills.return_value = []
    registry.get_effective_tools.return_value = []
    registry._skills_dir = None

    node = AgentExecutionNode(model=CapturingModel(), registry=registry)
    state = {
        "current_agent": "planning-coordinator",
        "reflection_count": 1,
        "critique": "Rewrite from scratch and attribute user-shared facts to the user.",
        "previous_attempts": ["Unauthorized direct assertion draft."],
        "messages": [
            HumanMessage(content="Earlier question", id="h1"),
            AIMessage(content="Earlier safe answer", id="a1"),
            HumanMessage(content="Current question", id="h2"),
            AIMessage(content="Unauthorized direct assertion draft.", id="a2_bad"),
        ],
    }

    res = await node.execute(state)
    assert res["next_step"] == "output_guardrail"
    sent = captured["messages"]
    assert isinstance(sent[0], SystemMessage)
    assert "# SELF-CORRECTION DIRECTIVE" in sent[0].content
    assert "Rewrite from scratch" in sent[0].content
    assert "Unauthorized direct assertion draft." in sent[0].content
    # Prompt handed to model must end with the HumanMessage (with ephemeral reminder), NOT the rejected AIMessage
    assert isinstance(sent[-1], HumanMessage)
    assert sent[-1].content.startswith("Current question")
    assert "SELF-CORRECTION NOTE" in sent[-1].content
    # Original HumanMessage in state["messages"] must never be mutated
    assert state["messages"][2].content == "Current question"
    assert all(getattr(m, "id", None) != "a2_bad" for m in sent)


def test_agent_execution_node_uses_injected_safety_policy_preamble():
    """Verifies AgentExecutionNode and GraphBuilder delegate preamble generation to safety_policy."""
    from yarvelle_core.engine.builder import GraphBuilder
    from yarvelle_core.schemas.manifest import SkillManifest
    from yarvelle_core.workflows.nodes.agent_execution_node import AgentExecutionNode

    skill = SkillManifest(
        id="project-planner",
        name="Project Planner",
        description="Structured milestone planning.",
    )
    agent = AgentManifest(
        id="planning-coordinator",
        title="Planning Coordinator",
        description="Coordinates planning tasks.",
        persona="You are a planning coordinator.",
        skills=["project-planner"],
        tools=[],
    )

    class CustomSafetyPolicy:
        def __init__(self):
            self.calls = []

        def get_preamble(self, manifest, skills=()):
            self.calls.append((manifest.id, [s.id for s in skills]))
            return "CUSTOM PACK PREAMBLE: Enforce domain pack contract."

    policy = CustomSafetyPolicy()
    registry = MagicMock()
    registry.get_loaded_skills.return_value = [skill]
    registry.get_skill.return_value = skill

    node = AgentExecutionNode(registry=registry, safety_policy=policy)
    rendered = node._resolve_system_prompt(agent, {"current_agent": "planning-coordinator"})
    assert "CUSTOM PACK PREAMBLE: Enforce domain pack contract." in rendered
    assert policy.calls == [("planning-coordinator", ["project-planner"])]

    builder = GraphBuilder(
        registry=registry,
        safety_policy=policy,
        use_dynamic_orchestrator=True,
    )
    captured_nodes = {}

    class SpyNode:
        pass

    # Verify GraphBuilder wires safety_policy into AgentExecutionNode when built without custom node override
    assert builder.safety_policy is policy
    # Instantiate directly via internal factory check by building graph
    graph = builder.create_graph()
    assert graph is not None
    # Inspect bound node in builder if possible, and verify custom fallback isn't needed when safety_policy is passed
    default_node = AgentExecutionNode(registry=registry)
    fallback_rendered = default_node._resolve_system_prompt(agent, {"current_agent": "planning-coordinator"})
    assert "CUSTOM PACK PREAMBLE" not in fallback_rendered
    assert "CORE SYSTEM SAFETY CONTRACT" in fallback_rendered


