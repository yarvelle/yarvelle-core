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

"""Regression tests for multi-step stream accumulation, degraded synthesis
disclaimer deduplication, and safe reference preamble stripping."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Sequence

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver

from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.builder import GraphBuilder
from yarvelle_core.engine.service import AgentExecutionService, strip_reference_doc_preamble
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec
from yarvelle_core.workflows.nodes.output_guardrail_node import OutputGuardrailNode
from yarvelle_core.workflows.nodes.response_synthesizer_node import (
    CANONICAL_DISCLAIMER,
    ResponseSynthesizerNode,
)

MAIN = "__main__"


class _ScriptedModel(BaseChatModel):
    scripts: Dict[str, List[BaseMessage]]

    @property
    def _llm_type(self) -> str:
        return "scripted-multi-step-test"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "_ScriptedModel":
        return self

    @staticmethod
    def _who(messages: List[BaseMessage]) -> str:
        system = next((m for m in messages if isinstance(m, SystemMessage)), None)
        text = str(system.content) if system is not None else ""
        marker = "You are the "
        if marker in text:
            return text.split(marker, 1)[1].split(" agent", 1)[0]
        return MAIN

    async def _reply(self, messages: List[BaseMessage]) -> BaseMessage:
        who = self._who(messages)
        queue = self.scripts.get(who) or []
        return queue.pop(0) if queue else AIMessage(content="")

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("async only")

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=await self._reply(messages))])

    async def _astream(
        self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        msg = await self._reply(messages)
        calls = getattr(msg, "tool_calls", None) or []
        chunk = AIMessageChunk(
            content=msg.content,
            tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i, "type": "tool_call_chunk"}
                for i, c in enumerate(calls)
            ],
        )
        if run_manager is not None and msg.content:
            await run_manager.on_llm_new_token(str(msg.content), chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


def _write_agent(root: Path, agent_id: str) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    data = {
        "id": agent_id,
        "title": agent_id.replace("-", " ").title(),
        "description": f"{agent_id} specialist",
        "persona": "persona.md",
        "tools": [],
        "skills": [],
    }
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (agent_dir / "persona.md").write_text(f"You are the {agent_id} agent.\n", encoding="utf-8")


def test_strip_reference_doc_preamble_preserves_leading_bold_markdown() -> None:
    bold_heading = "**Summary:**\n- Item 1\n- Item 2"
    assert strip_reference_doc_preamble(bold_heading) == bold_heading

    with_preamble = "**Based on the provided reference document,** here are your options."
    assert strip_reference_doc_preamble(with_preamble) == "Here are your options."


def test_output_guardrail_preserves_leading_bold_markdown() -> None:
    node = OutputGuardrailNode()
    result = asyncio.run(
        node.execute({"output": "**Action Plan:**\n- Verify details.", "messages": []})
    )
    assert result["output"].startswith("**Action Plan:**")
    assert not result["output"].startswith("Action Plan:**")


def test_degraded_multi_agent_synthesis_strips_constituent_middle_disclaimers() -> None:
    node = ResponseSynthesizerNode(
        agent_titles={
            "budget-planner": "Budget Planner",
            "trip-organizer": "Trip Organizer",
        }
    )
    state = {
        "output": "",
        "messages": [],
        "specialist_outputs": {
            "budget-planner": (
                "Keep hotel spend under $200/night.\n\n"
                "*Disclaimer: Yarvelle Core agents provide automated computational assistance.*"
            ),
            "trip-organizer": (
                "Book morning trains between cities.\n\n"
                f"{CANONICAL_DISCLAIMER}"
            ),
        },
    }
    synthesized = node.synthesize_response(state)
    body_without_canonical = synthesized[: -len(CANONICAL_DISCLAIMER)].strip()
    assert "disclaimer:" not in body_without_canonical.lower()
    assert "**Budget Planner:** Keep hotel spend under $200/night." in synthesized
    assert "**Trip Organizer:** Book morning trains between cities." in synthesized
    assert synthesized.endswith(CANONICAL_DISCLAIMER)


def test_multi_step_delegation_resets_pre_tool_preamble_and_disclaimer(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "budget-planner")
    _write_agent(agents_dir, "trip-organizer")
    registry = AgentRegistry(agents_dir=agents_dir)
    spec = PackOrchestrationSpec(default_agent="budget-planner")

    pre_tool_call = AIMessage(
        content=(
            "Let me coordinate with both specialists.\n\n"
            "*Disclaimer: Preliminary routing note.*"
        ),
        tool_calls=[
            {"name": "task", "id": "t1", "args": {"subagent_type": "budget-planner", "description": "budget"}},
            {"name": "task", "id": "t2", "args": {"subagent_type": "trip-organizer", "description": "itinerary"}},
        ],
    )
    composed_answer = AIMessage(
        content="**Coordinated Plan:**\n- Cap lodging at $200/night.\n- Take the 9am express train."
    )
    model = _ScriptedModel(
        scripts={
            MAIN: [pre_tool_call, composed_answer],
            "budget-planner": [AIMessage(content="Cap lodging at $200/night.")],
            "trip-organizer": [AIMessage(content="Take the 9am express train.")],
        }
    )

    async def _noop_sink(_payload: Any) -> None:
        return None

    checkpointer = MemorySaver()
    graph = GraphBuilder(
        model=model,
        checkpointer=checkpointer,
        registry=registry,
        orchestration=spec,
        orchestration_audit_sink=_noop_sink,
        turn_task_sink=_noop_sink,
    ).build()

    service = AgentExecutionService(
        model=model,
        graph=graph,
        checkpointer=checkpointer,
        workspace_root=tmp_path,
        orchestration=spec,
        registry=registry,
        output_release="buffered",
    )

    async def _run() -> List[Dict[str, Any]]:
        return [
            ev
            async for ev in service.execute_turn(
                thread_id="thread-multi-step-1",
                prompt="Plan my trip and budget",
                agent_id=None,
            )
        ]

    events = asyncio.run(_run())
    done = next(ev for ev in events if ev.get("type") == "done")
    full_text = done["fullText"]

    assert full_text.startswith("**Coordinated Plan:**")
    assert "Let me coordinate with both specialists." not in full_text
    assert "Preliminary routing note." not in full_text
    tokens = "".join(ev.get("delta", "") for ev in events if ev.get("type") == "token")
    assert tokens == full_text
