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

"""Per-turn delegation reminder for the main agent (``orchestration.delegation.reminder``).

Some local models ignore delegation rules that sit only in the system prompt
once a conversation has history. A pack can add a short reminder to the copy
of the latest user message the main agent reads. The reminder is model input
only: the checkpoint and the turn's returned messages keep the user's words.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pytest
import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import ValidationError

from tests.test_hybrid_routing import ScriptedModel, Sink, _write_agent
from yarvelle_core.agents import AgentRegistry
from yarvelle_core.engine.orchestration import HybridRouter
from yarvelle_core.engine.orchestration.reminder import (
    add_reminder,
    is_follow_up,
    main_agent_messages,
    reminder_from_spec,
)
from yarvelle_core.schemas.orchestration import DelegationReminderSpec, DelegationSpec, PackOrchestrationSpec

REMINDER = "(Follow-up: apply the hand-off rules to this new message.)"
T1 = "Plan a weekend trip."
T2 = "What would that cost?"


class RecordingModel(ScriptedModel):
    """Scripted model that records the messages of every call."""

    seen: List[List[BaseMessage]] = []

    def _record(self, messages: List[BaseMessage]) -> None:
        self.seen.append(list(messages))

    def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        self._record(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        self._record(messages)
        return await super()._agenerate(messages, stop, run_manager, **kwargs)


def _last_human(messages: Sequence[BaseMessage]) -> HumanMessage:
    return [m for m in messages if isinstance(m, HumanMessage)][-1]


def _spec(reminder: Optional[Dict[str, Any]] = None) -> PackOrchestrationSpec:
    data: Dict[str, Any] = {"default_agent": "budget-planner"}
    if reminder is not None:
        data["delegation"] = {"reminder": reminder}
    return PackOrchestrationSpec.model_validate(data)


@pytest.fixture()
def registry(tmp_path: Path) -> AgentRegistry:
    agents = tmp_path / "agents"
    _write_agent(agents, "budget-planner")
    _write_agent(agents, "trip-organizer")
    return AgentRegistry(agents_dir=agents)


HISTORY: List[BaseMessage] = [HumanMessage(content=T1), AIMessage(content="Two nights by the lake.")]


# ------------------------------------------------------------------ schema


def test_reminder_is_off_by_default() -> None:
    spec = PackOrchestrationSpec(default_agent="budget-planner")
    assert spec.delegation.reminder is None
    assert reminder_from_spec(spec.delegation.reminder) is None


def test_reminder_parses_from_pack_yaml_shape() -> None:
    spec = _spec({"text": REMINDER})
    assert spec.delegation.reminder == DelegationReminderSpec(text=REMINDER, when="follow_up")
    assert _spec({"text": REMINDER, "when": "always"}).delegation.reminder.when == "always"


@pytest.mark.parametrize(
    "bad",
    [{"text": ""}, {"text": "   "}, {"text": "x" * 2001}, {"text": REMINDER, "when": "sometimes"}, {"text": REMINDER, "extra": 1}, {}],
    ids=["empty", "blank", "too-long", "bad-when", "unknown-key", "no-text"],
)
def test_reminder_is_strict(bad: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _spec(bad)


def test_delegation_without_reminder_still_parses() -> None:
    assert DelegationSpec(instructions="Hand off budgets.").reminder is None


@pytest.mark.parametrize(
    "path",
    [
        Path(__file__).resolve().parents[2] / "schemas" / "pack.schema.json",
        Path(__file__).resolve().parents[1] / "src" / "yarvelle_core" / "schemas" / "pack.schema.json",
    ],
)
def test_committed_pack_schema_includes_reminder(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    props = schema["$defs"]["DelegationReminderSpec"]["properties"]
    assert set(props) == {"text", "when"}
    assert schema["$defs"]["DelegationReminderSpec"]["additionalProperties"] is False


# ------------------------------------------------------------------ message helpers


def test_follow_up_needs_an_earlier_reply_and_the_user_last() -> None:
    assert not is_follow_up([])
    assert not is_follow_up([SystemMessage(content="s"), HumanMessage(content=T1)])
    assert not is_follow_up(HISTORY)
    tool_turn = [HumanMessage(content=T1), AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]), ToolMessage(content="r", tool_call_id="1")]
    assert not is_follow_up(tool_turn)
    assert is_follow_up([*HISTORY, HumanMessage(content=T2)])


def test_add_reminder_changes_only_a_copy_of_the_last_user_message() -> None:
    last = HumanMessage(content=T2, id="h2")
    messages = [*HISTORY, last]
    out = add_reminder(messages, REMINDER)
    assert out[-1].content == f"{T2}\n\n{REMINDER}"
    assert out[-1].id == "h2"
    assert out[:-1] == messages[:-1]
    assert last.content == T2 and messages[-1] is last


def test_add_reminder_appends_a_text_block_to_multipart_content() -> None:
    parts = [{"type": "text", "text": T2}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]
    out = add_reminder([*HISTORY, HumanMessage(content=list(parts))], REMINDER)
    assert out[-1].content == [*parts, {"type": "text", "text": REMINDER}]


def test_spec_reminder_follow_up_vs_always() -> None:
    first = [HumanMessage(content=T1)]
    follow = [*HISTORY, HumanMessage(content=T2)]
    on_follow_up = reminder_from_spec(DelegationReminderSpec(text=REMINDER))
    always = reminder_from_spec(DelegationReminderSpec(text=REMINDER, when="always"))
    assert main_agent_messages(first, {}, on_follow_up) == first
    assert _last_human(main_agent_messages(follow, {}, on_follow_up)).content.endswith(REMINDER)
    assert _last_human(main_agent_messages(first, {}, always)).content.endswith(REMINDER)
    # Never after a reply or tool result: the user must have spoken last.
    assert main_agent_messages(HISTORY, {}, always) == HISTORY


def test_no_reminder_leaves_messages_untouched() -> None:
    follow = [*HISTORY, HumanMessage(content=T2)]
    assert main_agent_messages(follow, {}, None) == follow


def test_hook_gets_messages_and_state_and_may_decline() -> None:
    seen: List[Any] = []

    def hook(messages: Sequence[BaseMessage], state: Mapping[str, Any]) -> Optional[str]:
        seen.append((len(messages), state.get("thread_id")))
        return None if state.get("thread_id") == "quiet" else "Hook reminder."

    follow = [*HISTORY, HumanMessage(content=T2)]
    assert main_agent_messages(follow, {"thread_id": "quiet"}, hook) == follow
    assert _last_human(main_agent_messages(follow, {"thread_id": "t"}, hook)).content.endswith("Hook reminder.")
    assert seen == [(3, "quiet"), (3, "t")]


# ------------------------------------------------------------------ router


def _model() -> RecordingModel:
    return RecordingModel(script=[AIMessage(content="About 400.")], seen=[])


def _run(router: HybridRouter, messages: List[BaseMessage]) -> Any:
    return asyncio.run(router.run({"messages": messages}, turn_id="turn-1"))


def test_router_sends_the_spec_reminder_on_a_follow_up(registry: AgentRegistry) -> None:
    model = _model()
    router = HybridRouter(registry=registry, model=model, spec=_spec({"text": REMINDER}), audit_sink=Sink())
    messages = [*HISTORY, HumanMessage(content=T2)]
    outcome = _run(router, messages)
    assert _last_human(model.seen[0]).content == f"{T2}\n\n{REMINDER}"
    # The turn's returned messages are only the new reply, never the copy.
    assert [m.content for m in outcome.messages] == ["About 400."]
    assert messages[-1].content == T2


def test_router_without_reminder_sends_the_users_words(registry: AgentRegistry) -> None:
    model = _model()
    router = HybridRouter(registry=registry, model=model, spec=_spec(), audit_sink=Sink())
    _run(router, [*HISTORY, HumanMessage(content=T2)])
    assert _last_human(model.seen[0]).content == T2


def test_router_hook_replaces_the_spec_text(registry: AgentRegistry) -> None:
    model = _model()
    router = HybridRouter(
        registry=registry, model=model, spec=_spec({"text": REMINDER}), audit_sink=Sink(),
        reminder=lambda messages, state: "Hook reminder.",
    )
    _run(router, [*HISTORY, HumanMessage(content=T2)])
    assert _last_human(model.seen[0]).content == f"{T2}\n\nHook reminder."


# ------------------------------------------------------------------ production service graph


def _service_workspace(tmp_path: Path) -> Path:
    agents = tmp_path / "ws" / "agents"
    _write_agent(agents, "budget-planner")
    _write_agent(agents, "trip-organizer")
    return tmp_path / "ws"


async def _two_turns(service: Any, saver: MemorySaver, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    import yarvelle_core.engine.service as service_module
    from yarvelle_core.config import settings
    from yarvelle_core.engine.builder import GraphBuilder

    async def capture(event: Any, **kwargs: Any) -> Any:
        return event

    async def tasks(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(service_module, "record_audit", capture)
    real_init = GraphBuilder.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        # In-memory sinks and checkpoints; everything else is the service's own build.
        kwargs.update(orchestration_audit_sink=Sink(), turn_task_sink=tasks, checkpointer=saver)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(GraphBuilder, "__init__", init)
    original_build = GraphBuilder.build
    monkeypatch.setattr(GraphBuilder, "build", lambda self, *a, **k: original_build(self, checkpointer=saver))
    for prompt in (T1, T2):
        events = [e async for e in service.execute_turn(thread_id="reminder-thread", prompt=prompt)]
        assert not [e for e in events if e.get("type") == "error"], events
    state = saver.get_tuple({"configurable": {"thread_id": "reminder-thread", "checkpoint_ns": ""}})
    return state.checkpoint["channel_values"]["messages"]


@pytest.mark.asyncio
async def test_service_graph_reminds_on_follow_up_and_saves_only_the_users_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yarvelle_core.engine.service import AgentExecutionService

    model = RecordingModel(script=[AIMessage(content="Two nights."), AIMessage(content="About 400.")], seen=[])
    spec = _spec({"text": REMINDER})
    service = AgentExecutionService(model=model, workspace_root=_service_workspace(tmp_path), orchestration=spec)
    saved = await _two_turns(service, MemorySaver(), monkeypatch, tmp_path)
    main_calls = [msgs for msgs in model.seen if any(isinstance(m, HumanMessage) for m in msgs)]
    firsts = [msgs for msgs in main_calls if _last_human(msgs).content.startswith(T1)]
    seconds = [msgs for msgs in main_calls if _last_human(msgs).content.startswith(T2)]
    assert firsts and all(REMINDER not in str(m.content) for msgs in firsts for m in msgs)
    assert seconds and _last_human(seconds[0]).content == f"{T2}\n\n{REMINDER}"
    humans = [m.content for m in saved if isinstance(m, HumanMessage)]
    assert humans == [T1, T2]
    assert all(REMINDER not in str(m.content) for m in saved)


@pytest.mark.asyncio
async def test_service_passes_a_python_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yarvelle_core.engine.service import AgentExecutionService

    calls: List[int] = []

    def hook(messages: Sequence[BaseMessage], state: Mapping[str, Any]) -> Optional[str]:
        calls.append(len(messages))
        return "Hook reminder." if is_follow_up(messages) else None

    model = RecordingModel(script=[AIMessage(content="Two nights."), AIMessage(content="About 400.")], seen=[])
    service = AgentExecutionService(
        model=model, workspace_root=_service_workspace(tmp_path), orchestration=_spec(), main_agent_reminder=hook,
    )
    saved = await _two_turns(service, MemorySaver(), monkeypatch, tmp_path)
    assert len(calls) == 2
    seconds = [msgs for msgs in model.seen if any(isinstance(m, HumanMessage) and str(m.content).startswith(T2) for m in msgs)]
    assert seconds and _last_human(seconds[0]).content == f"{T2}\n\nHook reminder."
    assert all("Hook reminder." not in str(m.content) for m in saved)


# ------------------------------------------------------------------ eval driver


def _eval_pack(tmp_path: Path, reminder: Optional[Dict[str, Any]]) -> Any:
    from tests.test_orch_eval_driver import write_pack
    from yarvelle_core.testing.orch_eval.pack import load_eval_pack

    root = write_pack(tmp_path / "pack")
    if reminder is not None:
        data = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))
        data["orchestration"]["delegation"] = {"reminder": reminder}
        (root / "pack.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_eval_pack(root)


def _two_turn_eval(pack: Any) -> List[List[BaseMessage]]:
    from langchain_core.callbacks import BaseCallbackHandler

    from tests.test_orch_eval_driver import TRIP_TURN, scenario
    from yarvelle_core.testing.orch_eval.driver import ScenarioRunner
    from yarvelle_core.testing.orch_eval.fake import FakeBackend

    inputs: List[List[BaseMessage]] = []

    class _Inputs(BaseCallbackHandler):
        def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:  # type: ignore[override]
            inputs.append(list(messages[0]))

    backend = FakeBackend()
    backend.model.callbacks = [_Inputs()]
    follow_up = {
        "user": T2,
        "expect": {"route": "main_agent", "agents_exactly": ["budget-planner"]},
        "fake": {"main": [{"task": ["budget-planner"]}, {"answer": "About 300."}], "agents": {"budget-planner": ["300."]}},
    }
    result = asyncio.run(ScenarioRunner(pack, backend).run(scenario([TRIP_TURN, follow_up])))
    assert result.passed, result.failures()
    return [msgs for msgs in inputs if any(isinstance(m, HumanMessage) and str(m.content).startswith(T2) for m in msgs)]


def test_eval_driver_applies_the_pack_yaml_reminder(tmp_path: Path) -> None:
    seconds = _two_turn_eval(_eval_pack(tmp_path, {"text": REMINDER}))
    main = [msgs for msgs in seconds if _last_human(msgs).content.startswith(T2)]
    assert main and _last_human(main[0]).content == f"{T2}\n\n{REMINDER}"


def test_eval_driver_without_reminder_is_unchanged(tmp_path: Path) -> None:
    seconds = _two_turn_eval(_eval_pack(tmp_path, None))
    assert seconds and all(REMINDER not in str(m.content) for msgs in seconds for m in msgs)


def test_eval_pack_can_supply_a_python_hook(tmp_path: Path) -> None:
    from yarvelle_core.testing.orch_eval.pack import EvalPack

    base = _eval_pack(tmp_path, None)

    @dataclasses.dataclass(frozen=True)
    class _Pack(EvalPack):
        def main_agent_reminder(self) -> Any:
            return lambda messages, state: "Hook reminder." if is_follow_up(messages) else None

    pack = _Pack(**{f.name: getattr(base, f.name) for f in dataclasses.fields(base)})
    assert base.main_agent_reminder() is None
    seconds = _two_turn_eval(pack)
    main = [msgs for msgs in seconds if _last_human(msgs).content.startswith(T2)]
    assert main and _last_human(main[0]).content == f"{T2}\n\nHook reminder."
