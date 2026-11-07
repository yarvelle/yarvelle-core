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

Faults declared on the scenario wrap the backend model for that turn. A turn
with ``restart_before`` rebuilds the graph on the same checkpointer (and can
exercise encrypted checkpoints). ``cancel_after_ms`` cancels the turn task
after the delay once hand-offs have started.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from yarvelle_core.testing.orch_eval.checks import CheckResult, PackView, check_turn
from yarvelle_core.testing.orch_eval.judge import (
    DEFAULT_JUDGE_SAMPLES,
    SameModelJudgeError,
    assert_distinct_models,
    can_enable_gate,
    score_turn,
    trace_summary_from_turn,
)
from yarvelle_core.testing.orch_eval.report import HARD_RULE_NAMES
from yarvelle_core.testing.orch_eval.faults import FaultInjectingFakeModel, FaultPlan
from yarvelle_core.testing.orch_eval.pack import EvalPack
from yarvelle_core.testing.orch_eval.schema import Scenario, Turn
from yarvelle_core.testing.orch_eval.trace import TaskRecord, TurnTrace

ROUTE_NODE = "supervisor"
TASK_EVENT_PREFIX = "task."
MAIN_AGENT_ID = "main-agent"

ROUTE_EVENT_PREFIX = "route."


@dataclass
class JudgeRunOptions:
    """How the optional LLM judge runs for a suite."""

    enabled: bool = False
    gate: bool = False
    samples: int = DEFAULT_JUDGE_SAMPLES
    agreement: Optional[float] = None
    allow_self_judge: bool = False
    rubrics_dir: Optional[Path] = None
    model: Any = None
    subject_model: str = ""
    judge_model: str = ""


@dataclass
class TurnResult:
    trace: TurnTrace
    checks: List[CheckResult]
    judge: Optional[Dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        return not any(c.failed for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "turn": self.trace.turn,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "trace": self.trace.to_dict(),
        }
        if self.judge is not None:
            out["judge"] = self.judge
        return out


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    backend: str
    turns: List[TurnResult] = field(default_factory=list)
    error: Optional[str] = None
    skipped_turns: int = 0
    sample: Optional[int] = None

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
            "sample": self.sample,
            "passed": self.passed,
            "error": self.error,
            "skipped_turns": self.skipped_turns,
            "failures": self.failures(),
            "turns": [t.to_dict() for t in self.turns],
        }


class _AuditCapture:
    def __init__(self) -> None:
        self.events: List[Any] = []
        self.fail_next: bool = False

    async def __call__(self, event: Any) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected audit write failure")
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
        judge: Optional[JudgeRunOptions] = None,
    ) -> None:
        self.pack = pack
        self.backend = backend
        self._checkpointer_factory = checkpointer_factory
        self.judge = judge or JudgeRunOptions()

    def _checkpointer(self, *, encrypt: bool = False) -> Any:
        if self._checkpointer_factory is not None:
            return self._checkpointer_factory()
        import os

        from langgraph.checkpoint.memory import MemorySaver

        from yarvelle_core.vault.checkpoints import (
            CheckpointKeyring,
            EncryptedCheckpointSerializer,
            EncryptionPreservingSaverMixin,
            checkpoint_encryption_enabled,
            checkpoint_serializer,
        )

        use_encrypt = encrypt or checkpoint_encryption_enabled()
        if not use_encrypt:
            return MemorySaver()

        # Same serializer production savers use, so scenarios exercise encrypted
        # checkpoints (and resume through them) when encryption is switched on.
        class _EncryptedMemorySaver(EncryptionPreservingSaverMixin, MemorySaver):
            pass

        if encrypt and not checkpoint_encryption_enabled():
            # Scenario asked for encryption without flipping process settings:
            # use an ephemeral keyring so the run stays self-contained.
            keyring = CheckpointKeyring.from_kek(os.urandom(32))
            serde = EncryptedCheckpointSerializer(keyring, allow_plaintext_reads=False)
            return _EncryptedMemorySaver(serde=serde)
        return _EncryptedMemorySaver(serde=checkpoint_serializer())

    def _spec(self, scenario: Scenario) -> Any:
        spec = self.pack.spec
        if scenario.limits is None:
            return spec
        updates = {}
        if scenario.limits.max_agents is not None:
            updates["max_agents"] = scenario.limits.max_agents
        if scenario.limits.agent_timeout_s is not None:
            updates["agent_timeout_s"] = scenario.limits.agent_timeout_s
        if scenario.limits.turn_timeout_s is not None:
            updates["turn_timeout_s"] = scenario.limits.turn_timeout_s
        if updates:
            limits = spec.limits.model_copy(update=updates)
            spec = spec.model_copy(update={"limits": limits})
        return spec

    def _view(self, spec: Any) -> PackView:
        return PackView(
            titles={a: info.title for a, info in self.pack.agents.items()},
            hidden=frozenset(self.pack.hidden_ids),
            max_agents=int(spec.limits.max_agents),
        )

    def _prompt_chars(self) -> int:
        """Characters the main agent sees for its prompt and subagent catalog.

        Deep Agents puts every delegatable agent's name and description into the
        ``task`` tool schema. Keeping that catalog short is what "prompt size
        stays bounded" means for a large registry.
        """
        from yarvelle_core.engine.orchestration.runtime import compose_main_prompt

        main = len(
            compose_main_prompt(
                None,
                getattr(self.pack.spec, "synthesis", None),
                getattr(self.pack.spec, "delegation", None),
            )
        )
        catalog = 0
        for spec in self.pack.registry.list_subagents():
            catalog += len(str(spec.get("name") or ""))
            catalog += len(str(spec.get("description") or ""))
        return main + catalog

    def _build_graph(self, scenario: Scenario, spec: Any, model: Any, audit: Any, turn_tasks: Any, checkpointer: Any) -> Any:
        from yarvelle_core.engine.builder import GraphBuilder

        return GraphBuilder(
            model=model,
            registry=self.pack.registry,
            # "builtin" runs without pack routes; the pack default still applies.
            orchestration=None if scenario.routing == "builtin" else spec,
            default_agent=spec.default_agent,
            include_main_agent=scenario.routing == "hybrid",
            orchestration_audit_sink=audit,
            turn_task_sink=turn_tasks,
            safety_policy=self.pack.safety_policy(),
            checkpointer=checkpointer,
        ).build()


    def _apply_judge(
        self,
        *,
        turn: Turn,
        trace: TurnTrace,
        checks: List[CheckResult],
        previous: Sequence[TurnTrace],
    ) -> tuple[List[CheckResult], Optional[Dict[str, Any]]]:
        """Score the turn with the LLM judge when enabled and layer-1 passed."""
        opts = self.judge
        if not opts.enabled or turn.judge is None:
            return checks, None
        hard_failed = any(
            c.failed
            and (c.name in HARD_RULE_NAMES or c.name.startswith("invariant"))
            for c in checks
        )
        # Drop the placeholder skip; we will append a real judge check.
        checks = [c for c in checks if not c.name.startswith("judge:")]
        name = f"judge:{turn.judge.rubric}"
        if hard_failed:
            checks.append(
                CheckResult(name, "skip", "layer-1 hard rules failed; judge not run")
            )
            return checks, None
        try:
            assert_distinct_models(
                opts.subject_model,
                opts.judge_model,
                allow_self_judge=opts.allow_self_judge,
            )
        except SameModelJudgeError as err:
            checks.append(CheckResult(name, "fail", str(err)))
            return checks, None
        from yarvelle_core.testing.orch_eval.backends import Role

        model = opts.model
        if model is None:
            model = self.backend.model_for(Role(kind="judge"))
        conversation = []
        for t in previous:
            conversation.append({"role": "user", "text": t.user})
            if t.answer:
                conversation.append({"role": "assistant", "text": t.answer})
        result = score_turn(
            model,
            rubric=turn.judge.rubric,
            criteria=turn.judge.criteria,
            min_score=turn.judge.min_score,
            user=turn.user,
            answer=trace.answer or "",
            trace_summary=trace_summary_from_turn(trace),
            conversation=conversation,
            samples=opts.samples,
            rubrics_dir=opts.rubrics_dir,
        )
        gated = bool(opts.gate and can_enable_gate(opts.agreement))
        gate_failed = False
        if gated and not result.unsure and result.score < turn.judge.min_score:
            gate_failed = True
        result.gated = gated
        result.gate_failed = gate_failed
        detail = (
            f"score={result.score} verdict={result.verdict}"
            + (" unsure" if result.unsure else "")
            + (f" (gate)" if gated else " (report-only)")
        )
        if gate_failed:
            checks.append(CheckResult(name, "fail", detail))
        elif gated:
            checks.append(CheckResult(name, "pass", detail))
        else:
            # Soft: never fails the turn.
            checks.append(CheckResult(name, "pass", detail))
        return checks, result.to_dict()

    async def run(self, scenario: Scenario) -> ScenarioResult:
        from yarvelle_core.testing.orch_eval.backends import Role

        result = ScenarioResult(scenario_id=scenario.id, title=scenario.title, backend=self.backend.name)
        if scenario.pack != self.pack.id:
            result.error = f"scenario wants pack {scenario.pack!r}, loaded pack is {self.pack.id!r}"
            result.skipped_turns = len(scenario.turns)
            return result
        if hasattr(self.backend, "begin_scenario"):
            self.backend.begin_scenario(pack_id=self.pack.id, scenario_id=scenario.id)
        if hasattr(self.backend, "set_agents"):
            self.backend.set_agents(self.pack.agent_ids)
        spec = self._spec(scenario)
        view = self._view(spec)
        audit = _AuditCapture()
        turn_tasks = _TurnTaskCapture()
        checkpointer = self._checkpointer(encrypt=scenario.encrypt_checkpoints)
        base_model = self.backend.model_for(Role(kind="main"))
        fault_model = FaultInjectingFakeModel(inner=base_model)
        fault_model.set_agents(self.pack.agent_ids)
        graph = self._build_graph(scenario, spec, fault_model, audit, turn_tasks, checkpointer)
        thread_id = f"orch-eval-{scenario.id}-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}

        traces: List[TurnTrace] = []
        for number, turn in enumerate(scenario.turns, start=1):
            if turn.restart_before:
                # New graph, same checkpointer and thread: resume mid-conversation.
                graph = self._build_graph(scenario, spec, fault_model, audit, turn_tasks, checkpointer)
            plan = FaultPlan.from_specs(scenario.faults_for(number))
            cancel_ms = turn.cancel_after_ms if turn.cancel_after_ms is not None else plan.cancel_after_ms
            fault_model.set_turn(number, plan)
            if plan.audit_error:
                audit.fail_next = True
            trace = await self._run_turn(
                graph, config, thread_id, number, turn, audit, turn_tasks, cancel_after_ms=cancel_ms
            )
            # Catalog size is fixed for the pack; record it on every turn so
            # budget.prompt_chars can bound large-registry scenarios.
            trace.prompt_chars = self._prompt_chars()
            cost = self.backend.cost_per_mtok.cost_usd(trace.input_tokens, trace.output_tokens)
            checks = check_turn(trace, turn, view, previous=traces, usd=cost)
            checks, judge_payload = self._apply_judge(
                turn=turn, trace=trace, checks=checks, previous=traces
            )
            traces.append(trace)
            result.turns.append(TurnResult(trace=trace, checks=checks, judge=judge_payload))
            # Expected cancels and expected errors are not run-stopping failures.
            if trace.error and turn.expect.error_matches is None and not turn.expect.cancelled:
                result.skipped_turns = len(scenario.turns) - number
                break
        if hasattr(self.backend, "flush"):
            self.backend.flush()
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
        *,
        cancel_after_ms: Optional[int] = None,
    ) -> TurnTrace:
        import asyncio

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

        async def _consume() -> None:
            nonlocal routed
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

        try:
            if cancel_after_ms is None:
                await _consume()
            else:
                task = asyncio.create_task(_consume())

                async def _cancel_when_ready() -> None:
                    deadline = time.perf_counter() + (cancel_after_ms / 1000.0)
                    while time.perf_counter() < deadline:
                        if any(e.get("state") == "started" for e in trace.status_events):
                            await asyncio.sleep(0.05)
                            break
                        await asyncio.sleep(0.01)
                    if not task.done():
                        task.cancel()

                watchdog = asyncio.create_task(_cancel_when_ready())
                try:
                    await task
                except asyncio.CancelledError:
                    trace.cancelled = True
                finally:
                    watchdog.cancel()
                    try:
                        await watchdog
                    except asyncio.CancelledError:
                        pass
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                    if task.cancelled() or trace.cancelled:
                        trace.cancelled = True
        except asyncio.CancelledError:
            trace.cancelled = True
        except Exception as err:  # the trace records the failure; checks report it
            if type(err).__name__ == "CancelledError" or "CancelledError" in type(err).__name__:
                trace.cancelled = True
            else:
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
        # Route and agent come from checkpoint state. The supervisor commits
        # route_decision before the main_agent node runs, so a mid-hand-off
        # cancel still leaves them on the checkpoint.
        trace.turn_tasks = [r.model_dump(mode="json") for r in turn_tasks.rows[tasks_start:]]
        records = _tasks_from_audit(turn_audit)
        trace.tasks = [t for t in records if "started" in t.states]
        trace.rejected_tasks = [t for t in records if "started" not in t.states]
        if trace.route == "main_agent" or (trace.cancelled and trace.tasks):
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
    *,
    samples: Optional[int] = None,
    judge: Optional[JudgeRunOptions] = None,
) -> List[ScenarioResult]:
    """Runs each scenario on a fresh backend and graph. Scenarios that do not
    list the backend are left out. Noisy backends run ``samples`` times
    (scenario default: 1 for fake/replay, 3 otherwise)."""
    results: List[ScenarioResult] = []
    for scenario in scenarios:
        backend = backend_factory()
        if backend.name not in scenario.backends:
            continue
        count = samples if samples is not None else scenario.samples_for(backend.name)  # type: ignore[arg-type]
        for sample_i in range(1, count + 1):
            if sample_i > 1:
                backend = backend_factory()
            result = await ScenarioRunner(pack, backend, judge=judge).run(scenario)
            result.sample = sample_i if count > 1 else None
            results.append(result)
    return results


__all__ = [
    "JudgeRunOptions",
    "ScenarioResult",
    "ScenarioRunner",
    "TurnResult",
    "run_scenarios",
]
