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

"""Multi-turn scenario driver for the orchestration eval harness.

Runs every turn of a scenario through the real graph from
:class:`GraphBuilder`, on one thread id per scenario so later turns see the
earlier ones through the checkpointer. Per turn it collects the graph state,
the custom stream events (``task_status`` and ``orchestration_notice``) and
the orchestration audit records, builds a :class:`TurnTrace` and checks it.

Each turn sends only what a caller sends: the user message, the explicit
agent pick (or none) and the turn's attachments. The graph itself clears the
previous turn's routing state, raises guardrail flags from the user's text
(through the pack's flag words) and writes the route audit records, so the
scenarios check the runtime's own behaviour.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from yarvelle_core.testing.orch_eval.checks import CheckResult, PackView, check_turn
from yarvelle_core.testing.orch_eval.pack import EvalPack
from yarvelle_core.testing.orch_eval.schema import Scenario, Turn
from yarvelle_core.testing.orch_eval.trace import TaskRecord, TurnTrace

ROUTE_NODE = "supervisor"
TASK_EVENT_PREFIX = "task."
MAIN_AGENT_ID = "main-agent"

ROUTE_EVENT_PREFIX = "route."


@dataclass
class TurnResult:
    trace: TurnTrace
    checks: List[CheckResult]

    @property
    def passed(self) -> bool:
        return not any(c.failed for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.trace.turn,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "trace": self.trace.to_dict(),
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    backend: str
    turns: List[TurnResult] = field(default_factory=list)
    error: Optional[str] = None
    skipped_turns: int = 0

    @property
    def passed(self) -> bool:
        return self.error is None and self.skipped_turns == 0 and all(t.passed for t in self.turns)

    def failures(self) -> List[str]:
        out = [f"error: {self.error}"] if self.error else []
        for t in self.turns:
            out.extend(f"turn {t.trace.turn}: {c.name}: {c.detail}" for c in t.checks if c.failed)
        if self.skipped_turns:
            out.append(f"{self.skipped_turns} later turn(s) not run")
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.scenario_id,
            "title": self.title,
            "backend": self.backend,
            "passed": self.passed,
            "error": self.error,
            "skipped_turns": self.skipped_turns,
            "failures": self.failures(),
            "turns": [t.to_dict() for t in self.turns],
        }


class _AuditCapture:
    def __init__(self) -> None:
        self.events: List[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


class _TurnTaskCapture:
    """In-memory stand-in for the ``turn_tasks`` table."""

    def __init__(self) -> None:
        self.rows: List[Any] = []

    async def __call__(self, rows: Sequence[Any]) -> None:
        self.rows.extend(rows)


def _route_label(decision: Optional[Dict[str, Any]]) -> Optional[str]:
    if not decision:
        return None
    source = decision.get("source")
    if source == "fixed_route":
        return f"fixed_route:{decision.get('route_id')}"
    if source == "default_agent":
        return f"default_agent:{decision.get('fallback_reason')}"
    return str(source) if source else None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _final_answer(messages: Sequence[Any], start: int) -> str:
    for message in reversed(list(messages)[start:]):
        if getattr(message, "type", "") != "ai":
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = _text(getattr(message, "content", ""))
        if text.strip():
            return text
    return ""


def _usage(output: Any) -> tuple[int, int]:
    usage = getattr(output, "usage_metadata", None) or {}
    try:
        return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    except AttributeError:
        return 0, 0


def _tasks_from_audit(events: Sequence[Any]) -> List[TaskRecord]:
    records: Dict[str, TaskRecord] = {}
    for event in events:
        kind = str(getattr(event, "event", ""))
        if not kind.startswith(TASK_EVENT_PREFIX) or not getattr(event, "task_id", None):
            continue
        task_id = str(event.task_id)
        record = records.get(task_id)
        if record is None:
            record = records[task_id] = TaskRecord(task_id=task_id, agent_id=str(event.agent_id))
        record.states.append(kind[len(TASK_EVENT_PREFIX):])
        if (getattr(event, "details", None) or {}).get("truncated"):
            record.truncated = True
    return list(records.values())


def _unique(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


class ScenarioRunner:
    """Runs scenarios against one eval pack on one backend."""

    def __init__(
        self,
        pack: EvalPack,
        backend: Any,
        *,
        checkpointer_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.pack = pack
        self.backend = backend
        self._checkpointer_factory = checkpointer_factory

    def _checkpointer(self) -> Any:
        if self._checkpointer_factory is not None:
            return self._checkpointer_factory()
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    def _spec(self, scenario: Scenario) -> Any:
        spec = self.pack.spec
        if scenario.limits is not None and scenario.limits.max_agents is not None:
            limits = spec.limits.model_copy(update={"max_agents": scenario.limits.max_agents})
            spec = spec.model_copy(update={"limits": limits})
        return spec

    def _view(self, spec: Any) -> PackView:
        return PackView(
            titles={a: info.title for a, info in self.pack.agents.items()},
            hidden=frozenset(self.pack.hidden_ids),
            max_agents=int(spec.limits.max_agents),
        )

    async def run(self, scenario: Scenario) -> ScenarioResult:
        from yarvelle_core.engine.builder import GraphBuilder
        from yarvelle_core.testing.orch_eval.backends import Role

        result = ScenarioResult(scenario_id=scenario.id, title=scenario.title, backend=self.backend.name)
        if scenario.pack != self.pack.id:
            result.error = f"scenario wants pack {scenario.pack!r}, loaded pack is {self.pack.id!r}"
            result.skipped_turns = len(scenario.turns)
            return result
        if hasattr(self.backend, "set_agents"):
            self.backend.set_agents(self.pack.agent_ids)
        spec = self._spec(scenario)
        view = self._view(spec)
        audit = _AuditCapture()
        turn_tasks = _TurnTaskCapture()
        checkpointer = self._checkpointer()
        graph = GraphBuilder(
            model=self.backend.model_for(Role(kind="main")),
            registry=self.pack.registry,
            orchestration=spec,
            orchestration_audit_sink=audit,
            turn_task_sink=turn_tasks,
            safety_policy=self.pack.safety_policy(),
            checkpointer=checkpointer,
        ).build()
        thread_id = f"orch-eval-{scenario.id}-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}

        traces: List[TurnTrace] = []
        for number, turn in enumerate(scenario.turns, start=1):
            trace = await self._run_turn(graph, config, thread_id, number, turn, audit, turn_tasks)
            cost = self.backend.cost_per_mtok.cost_usd(trace.input_tokens, trace.output_tokens)
            checks = check_turn(trace, turn, view, previous=traces, usd=cost)
            traces.append(trace)
            result.turns.append(TurnResult(trace=trace, checks=checks))
            if trace.error:
                result.skipped_turns = len(scenario.turns) - number
                break
        return result

    async def _run_turn(
        self,
        graph: Any,
        config: Dict[str, Any],
        thread_id: str,
        number: int,
        turn: Turn,
        audit: _AuditCapture,
        turn_tasks: _TurnTaskCapture,
    ) -> TurnTrace:
        from langchain_core.messages import HumanMessage

        from yarvelle_core.engine.service import is_subagent_token

        trace = TurnTrace(turn=number, user=turn.user)
        if hasattr(self.backend, "load_turn"):
            self.backend.load_turn(number, turn.fake)
        before = await graph.aget_state(config)
        start_messages = len((before.values or {}).get("messages") or []) if before is not None else 0
        audit_start = len(audit.events)
        tasks_start = len(turn_tasks.rows)

        attachments = list(turn.input.attachments) if turn.input is not None else []
        state_in: Dict[str, Any] = {
            "messages": [HumanMessage(content=turn.user)],
            "thread_id": thread_id,
            "explicit_agent": turn.explicit_agent,
            "attachments": attachments,
        }

        routed = False
        stream_notices: List[Dict[str, Any]] = []
        agent_ids = set(self.pack.agent_ids)
        started = time.perf_counter()
        try:
            async for event in graph.astream_events(state_in, config=config, version="v2"):
                kind = event.get("event")
                meta = event.get("metadata") or {}
                node = meta.get("langgraph_node")
                name = event.get("name")
                top_level = "|" not in str(meta.get("langgraph_checkpoint_ns") or "")
                if kind == "on_chain_start" and node and name == node and top_level:
                    if not trace.nodes or trace.nodes[-1] != node:
                        trace.nodes.append(node)
                elif kind == "on_chain_end" and node == ROUTE_NODE and name == ROUTE_NODE:
                    routed = True
                elif kind == "on_custom_event":
                    data = event.get("data") or {}
                    if name == "task_status" and isinstance(data, dict):
                        trace.status_events.append(dict(data))
                    elif name == "orchestration_notice" and isinstance(data, dict):
                        stream_notices.append(dict(data))
                elif kind == "on_chat_model_start":
                    if "suggestion" in (event.get("tags") or []):
                        continue
                    trace.model_calls += 1
                    if not routed:
                        trace.model_calls_before_route += 1
                elif kind == "on_chat_model_end":
                    i, o = _usage((event.get("data") or {}).get("output"))
                    trace.input_tokens += i
                    trace.output_tokens += o
                elif kind == "on_chat_model_stream":
                    chunk = (event.get("data") or {}).get("chunk")
                    text = _text(getattr(chunk, "content", ""))
                    who = meta.get("lc_agent_name")
                    if text and who in agent_ids and who != MAIN_AGENT_ID and node == "main_agent" and not is_subagent_token(meta):
                        trace.subagent_token_leaks.append(f"{who}: {text[:60]}")
        except Exception as err:  # the trace records the failure; checks report it
            trace.error = f"{type(err).__name__}: {err}"
        trace.latency_ms = (time.perf_counter() - started) * 1000

        after = await graph.aget_state(config)
        values: Dict[str, Any] = dict(after.values or {}) if after is not None else {}
        decision = values.get("route_decision")
        trace.route = _route_label(decision)
        trace.route_agent = (decision or {}).get("agent_id")
        trace.guardrail_flags = [str(f) for f in values.get("guardrail_flags") or []]

        turn_audit = audit.events[audit_start:]
        trace.route_events = [
            str(e.event) for e in turn_audit if str(getattr(e, "event", "")).startswith(ROUTE_EVENT_PREFIX)
        ]
        trace.turn_tasks = [r.model_dump(mode="json") for r in turn_tasks.rows[tasks_start:]]
        records = _tasks_from_audit(turn_audit)
        trace.tasks = [t for t in records if "started" in t.states]
        trace.rejected_tasks = [t for t in records if "started" not in t.states]
        if trace.route == "main_agent":
            trace.agents = _unique([t.agent_id for t in trace.tasks])
        elif "agent" in trace.nodes and trace.route_agent:
            trace.agents = [str(trace.route_agent)]

        notices: List[Dict[str, Any]] = []
        seen = set()
        for n in [*(values.get("orchestration_notices") or []), *stream_notices]:
            key = (n.get("code"), tuple(n.get("agent_ids") or []))
            if key not in seen:
                seen.add(key)
                notices.append({"code": n.get("code"), "agent_ids": list(n.get("agent_ids") or []), "message": n.get("message", "")})
        trace.notices = notices
        trace.provenance = [dict(p) for p in (values.get("provenance") or [])]
        trace.answer = _final_answer(values.get("messages") or [], start_messages)
        if hasattr(self.backend, "problems"):
            trace.script_problems = list(self.backend.problems(number))
        return trace


async def run_scenarios(
    scenarios: Sequence[Scenario],
    pack: EvalPack,
    backend_factory: Callable[[], Any],
) -> List[ScenarioResult]:
    """Runs each scenario on a fresh backend and graph. Scenarios that do not
    list the backend are left out."""
    results: List[ScenarioResult] = []
    for scenario in scenarios:
        backend = backend_factory()
        if backend.name not in scenario.backends:
            continue
        results.append(await ScenarioRunner(pack, backend).run(scenario))
    return results


__all__ = ["ScenarioResult", "ScenarioRunner", "TurnResult", "run_scenarios"]
