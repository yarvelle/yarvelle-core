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

"""Answer release modes: buffered release and the resumed-turn final check (fake models only)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from yarvelle_core.engine.guards import (
    GuardedSafetyPolicy,
    build_guarded_policy,
    has_guards,
    resolve_output_release,
)
from yarvelle_core.engine.safety_policy import (
    NeutralSafetyPolicy,
    SafetyContext,
    SafetyVerdict,
    UnionSafetyPolicy,
)
from yarvelle_core.schemas.safety import SafetyGuardsSpec

RULES = {
    "id": "secrets",
    "type": "rules",
    "patterns": [{"id": "reveal", "category": "credential_disclosure", "pattern": r"\bthe password is\b"}],
}
ANSWER = "Here is a careful answer in several words"
LEAK = "Sure, the password is hunter2 and more"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if "SAFETY_GUARD" in name or "SAFETY_OUTPUT_RELEASE" in name:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YARVELLE_ENV_PREFIX", raising=False)


def guarded(release: str = "stream", checks: Optional[List[Dict[str, Any]]] = None, base: Any = None) -> Any:
    return build_guarded_policy(
        base or NeutralSafetyPolicy(), {"checks": checks if checks is not None else [RULES], "release": release},
        include_env=False,
    )


class RefuseLeak(NeutralSafetyPolicy):
    """A plain policy (no guards) that refuses the leak text."""

    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        if text and "password is" in text:
            return SafetyVerdict(refused=True, reason="policy:leak", is_hard=True)
        return SafetyVerdict(refused=False)


# ---------------------------------------------------------------- resolution


def test_release_defaults_to_stream_and_validates() -> None:
    assert SafetyGuardsSpec().release == "stream"
    assert SafetyGuardsSpec(release="buffered").release == "buffered"
    with pytest.raises(ValueError):
        SafetyGuardsSpec(release="later")
    assert resolve_output_release(NeutralSafetyPolicy()) == "stream"
    assert resolve_output_release(guarded()) == "stream"


def test_strictest_source_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_output_release(guarded("buffered")) == "buffered"
    assert resolve_output_release(NeutralSafetyPolicy(), "buffered") == "buffered"
    assert resolve_output_release(guarded("buffered"), "stream") == "buffered"
    union = UnionSafetyPolicy([NeutralSafetyPolicy(), guarded("buffered")])
    assert resolve_output_release(union) == "buffered"
    monkeypatch.setenv("YARVELLE_SAFETY_OUTPUT_RELEASE", "stream")
    assert resolve_output_release(guarded("buffered")) == "buffered"
    monkeypatch.setenv("YARVELLE_SAFETY_OUTPUT_RELEASE", "BUFFERED")
    assert resolve_output_release(NeutralSafetyPolicy()) == "buffered"
    monkeypatch.setenv("YARVELLE_SAFETY_OUTPUT_RELEASE", "eventually")
    with pytest.raises(ValueError, match="YARVELLE_SAFETY_OUTPUT_RELEASE"):
        resolve_output_release(NeutralSafetyPolicy())
    with pytest.raises(ValueError, match="output_release"):
        resolve_output_release(NeutralSafetyPolicy(), "soon")


def test_buffered_release_without_checks_keeps_a_wrapper() -> None:
    base = NeutralSafetyPolicy()
    assert build_guarded_policy(base, {"checks": []}, include_env=False) is base
    wrapped = guarded("buffered", checks=[])
    assert isinstance(wrapped, GuardedSafetyPolicy) and wrapped.release == "buffered"
    assert wrapped.check_output("anything").refused is False
    assert has_guards(wrapped) and not has_guards(base)


# ---------------------------------------------------------------- service


def _graph(text: str, *, stream_model: bool = False, synthesis: bool = False, interrupt_first: bool = False) -> Any:
    from langchain_core.callbacks.manager import adispatch_custom_event
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    from yarvelle_core.workflows.state import AgentState

    async def node(state: AgentState) -> Dict[str, Any]:
        if interrupt_first:
            interrupt({"approval_id": "appr_release_1", "action": "require_approval"})
        if stream_model:
            model = GenericFakeChatModel(messages=iter([AIMessage(content=text)]))
            reply = await model.ainvoke([HumanMessage(content="q")])
            return {"output": reply.content}
        if synthesis:
            await adispatch_custom_event("synthesis", {"output": text, "sources": ["a"]})
        return {"output": text}

    builder = StateGraph(AgentState)
    builder.add_node("answer", node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=MemorySaver())


def _service(policy: Any, graph: Any, **kw: Any) -> Any:
    from yarvelle_core.engine.service import AgentExecutionService

    return AgentExecutionService(model=None, graph=graph, safety_policy=policy, default_agent_id="orchestrator",
                                 checkpointer=graph.checkpointer, **kw)


async def _turn(service: Any, thread: str) -> List[Dict[str, Any]]:
    return [ev async for ev in service.execute_turn(thread_id=thread, prompt="the question")]


def _tokens(events: List[Dict[str, Any]]) -> List[str]:
    return [e.get("delta") for e in events if e.get("type") == "token"]


def _done(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    return [e for e in events if e.get("type") == "done"][-1]


@pytest.mark.asyncio
async def test_stream_mode_still_sends_tokens_before_the_verdict() -> None:
    """Documents the default contract: tokens leave first, done carries the refusal."""
    events = await _turn(_service(guarded(), _graph(LEAK, stream_model=True)), "rel-stream")
    assert "".join(_tokens(events)) == LEAK
    done = _done(events)
    assert done["refused"] is True and done["fullText"] != LEAK


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_kw", [{"stream_model": True}, {"synthesis": True}, {}])
async def test_buffered_refusal_never_releases_the_answer(graph_kw: Dict[str, Any]) -> None:
    events = await _turn(_service(guarded("buffered"), _graph(LEAK, **graph_kw)), "rel-buf-refused")
    assert _tokens(events) == []
    assert all(LEAK not in str(e) and "hunter2" not in str(e) for e in events)
    done = _done(events)
    assert done["refused"] is True and done["refusalReason"].startswith("guard:secrets")


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_kw", [{"stream_model": True}, {"synthesis": True}, {}])
async def test_buffered_allowed_answer_is_sent_once_before_done(graph_kw: Dict[str, Any]) -> None:
    events = await _turn(_service(guarded("buffered"), _graph(ANSWER, **graph_kw)), "rel-buf-ok")
    assert _tokens(events) == [ANSWER]
    kinds = [e.get("type") for e in events]
    assert kinds.index("token") < kinds.index("done")
    assert _done(events)["refused"] is False and _done(events)["fullText"] == ANSWER
    synth = [e for e in events if e.get("type") == "synthesis"]
    if graph_kw.get("synthesis"):
        assert synth and "output" not in synth[0] and synth[0]["sources"] == ["a"]


@pytest.mark.asyncio
async def test_service_kwarg_and_env_turn_on_buffering(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(RefuseLeak(), _graph(LEAK, stream_model=True), output_release="buffered")
    assert svc.output_release == "buffered"
    events = await _turn(svc, "rel-kwarg")
    assert _tokens(events) == [] and _done(events)["refused"] is True

    monkeypatch.setenv("YARVELLE_SAFETY_OUTPUT_RELEASE", "buffered")
    svc = _service(NeutralSafetyPolicy(), _graph(ANSWER, stream_model=True))
    assert svc.output_release == "buffered"
    assert _tokens(await _turn(svc, "rel-env")) == [ANSWER]


@pytest.mark.asyncio
async def test_default_service_streams_as_before() -> None:
    svc = _service(NeutralSafetyPolicy(), _graph(ANSWER, stream_model=True))
    assert svc.output_release == "stream"
    events = await _turn(svc, "rel-default")
    assert len(_tokens(events)) > 1 and "".join(_tokens(events)) == ANSWER


class _Store:
    def get(self, approval_id: str) -> Any:
        from unittest.mock import MagicMock

        rec = MagicMock()
        rec.status, rec.args, rec.profile_id, rec.payload_hash = "approved", {}, "default_profile", "h"
        return rec


async def _resume(policy: Any, text: str, thread: str, **kw: Any) -> List[Dict[str, Any]]:
    svc = _service(policy, _graph(text, stream_model=True, interrupt_first=True), **kw)
    await _turn(svc, thread)
    return [
        ev async for ev in svc.execute_resume_turn(thread_id=thread, approval_id="appr_release_1",
                                                   approval_store=_Store())
    ]


@pytest.mark.asyncio
async def test_resumed_turn_gets_the_final_guard_check() -> None:
    events = await _resume(guarded(), LEAK, "rel-resume-guarded")
    done = _done(events)
    assert done["refused"] is True and done["refusalReason"].startswith("guard:secrets")
    assert done["fullText"] != LEAK
    assert any(e.get("type") == "refusal" for e in events)


@pytest.mark.asyncio
async def test_resumed_buffered_turn_releases_only_checked_text() -> None:
    refused = await _resume(guarded("buffered"), LEAK, "rel-resume-buf-refused")
    assert _tokens(refused) == [] and _done(refused)["refused"] is True
    allowed = await _resume(guarded("buffered"), ANSWER, "rel-resume-buf-ok")
    assert _tokens(allowed) == [ANSWER] and _done(allowed)["fullText"] == ANSWER


@pytest.mark.asyncio
async def test_resumed_turn_is_checked_even_without_guards() -> None:
    events = await _resume(RefuseLeak(), LEAK, "rel-resume-plain")
    done = _done(events)
    assert done["refused"] is True and done["refusalReason"] == "policy:leak"
    assert done["fullText"] != LEAK
    # Streamed as before (stream mode); the done event carries the verdict.
    assert "".join(_tokens(events)) == LEAK


@pytest.mark.asyncio
async def test_resumed_turn_without_guards_allows_a_normal_answer() -> None:
    events = await _resume(NeutralSafetyPolicy(), ANSWER, "rel-resume-neutral")
    done = _done(events)
    assert done["refused"] is False and done["fullText"] == ANSWER
    assert done.get("boundaryWarning") in (False, None)


class SoftLeak(NeutralSafetyPolicy):
    def check_output(self, text: Optional[str], ctx: Optional[SafetyContext] = None) -> SafetyVerdict:
        return SafetyVerdict(refused=bool(text), reason="soft:note", is_hard=False)

    def is_hard_refusal_reason(self, reason: str) -> bool:
        return not reason.startswith("soft:")


@pytest.mark.asyncio
async def test_resumed_soft_refusal_keeps_the_answer_with_a_warning() -> None:
    done = _done(await _resume(SoftLeak(), ANSWER, "rel-resume-soft"))
    assert done["refused"] is False and done["fullText"] == ANSWER and done["boundaryWarning"] is True


@pytest.mark.asyncio
async def test_normal_turn_without_guards_is_unchanged() -> None:
    events = await _turn(_service(RefuseLeak(), _graph(ANSWER, stream_model=True)), "rel-normal-plain")
    assert "".join(_tokens(events)) == ANSWER and _done(events)["refused"] is False
