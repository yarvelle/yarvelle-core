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

"""Scenario schema for the orchestration eval harness.

One YAML file describes one conversation: an ordered list of user turns, each
with the routing, delegation and reply expectations to check. Every model
uses ``extra="forbid"`` so a misspelled key fails the load instead of being
silently ignored. The format is versioned through the top-level ``schema``
field.
"""

from __future__ import annotations

import re
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

BackendName = Literal["fake", "replay", "ollama", "provider"]
TaskState = Literal["completed", "failed", "timed_out", "cancelled"]
OverlapMode = Literal["equal", "subset", "overlap"]

SCENARIO_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
AGENT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
ROUTE_PATTERN = (
    r"^(main_agent|user_selected|model_classified|fixed_route:[a-z0-9_-]{1,64}"
    r"|default_agent:[a-z0-9_-]{1,64})$"
)

RoutingMode = Literal["hybrid", "classifier", "builtin"]
"""How the scenario's graph routes unpinned turns.

``hybrid``: pack fixed routes, then the main agent (the default).
``classifier``: pack fixed routes, then a routing model picks one agent.
``builtin``: no pack routes; core's built-in document route, then a routing
model picks one agent. The pack's default agent still applies.
"""

AgentId = str

_AGENT_ID_RE = re.compile(AGENT_ID_PATTERN)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _agent_ids(values: list[str]) -> list[str]:
    bad = [v for v in values if not _AGENT_ID_RE.match(v)]
    if bad:
        raise ValueError(f"invalid agent id(s): {bad}")
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate agent id(s) in {values}")
    return values


class TurnInput(_Strict):
    """Extra turn inputs and input-side expectations.

    ``guardrail_flag`` is the flag the input guardrail is expected to raise
    from the user's text (through the pack's ``guardrail_flags`` words); the
    harness does not inject it. ``attachments`` are sent with the turn.
    """

    guardrail_flag: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    attachments: list[str] = Field(default_factory=list)


class SameAgentsAsTurn(_Strict):
    """Compares this turn's agents with an earlier turn (1-based)."""

    turn: int = Field(..., ge=1)
    mode: OverlapMode = "equal"


class NoticeExpectation(_Strict):
    code: str = Field(..., min_length=1)
    agent_ids: list[AgentId] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_ids(self) -> "NoticeExpectation":
        _agent_ids(self.agent_ids)
        return self


class AnswerExpectation(_Strict):
    """Reply text checks. Entries are case-insensitive substrings, or ``/regex/``."""

    must_mention: list[str] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)
    no_slug_leak: bool = True


class ProvenanceExpectation(_Strict):
    must_cite: list[AgentId] = Field(default_factory=list)
    must_not_cite: list[AgentId] = Field(default_factory=list)
    missing: list[AgentId] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ProvenanceExpectation":
        for ids in (self.must_cite, self.must_not_cite, self.missing):
            _agent_ids(ids)
        clash = set(self.must_cite) & set(self.must_not_cite)
        if clash:
            raise ValueError(f"agents both required and forbidden as citations: {sorted(clash)}")
        return self


class BudgetExpectation(_Strict):
    latency_ms_p95: Optional[int] = Field(default=None, gt=0)
    tokens: Optional[int] = Field(default=None, gt=0)
    usd: Optional[float] = Field(default=None, ge=0)
    model_calls: Optional[int] = Field(default=None, ge=0)


class TurnExpectation(_Strict):
    """What a single turn must (and must not) do."""

    route: Optional[str] = Field(default=None, pattern=ROUTE_PATTERN)
    agents_exactly: Optional[list[AgentId]] = None
    agents_all_of: list[AgentId] = Field(default_factory=list)
    agents_any_of: list[AgentId] = Field(default_factory=list)
    agents_forbidden: list[AgentId] = Field(default_factory=list)
    min_task_calls: Optional[int] = Field(default=None, ge=0)
    max_task_calls: Optional[int] = Field(default=None, ge=0)
    same_agents_as_turn: Optional[SameAgentsAsTurn] = None
    task_states: dict[AgentId, TaskState] = Field(default_factory=dict)
    notices: Optional[list[Union[str, NoticeExpectation]]] = None
    answer: Optional[AnswerExpectation] = None
    provenance: Optional[ProvenanceExpectation] = None
    deliberation: Optional[bool] = None
    model_calls_before_route: Optional[int] = Field(default=None, ge=0)
    budget: Optional[BudgetExpectation] = None

    @model_validator(mode="after")
    def _check(self) -> "TurnExpectation":
        for ids in (
            self.agents_exactly or [],
            self.agents_all_of,
            self.agents_any_of,
            self.agents_forbidden,
            list(self.task_states),
        ):
            _agent_ids(ids)
        required = set(self.agents_exactly or []) | set(self.agents_all_of)
        clash = required & set(self.agents_forbidden)
        if clash:
            raise ValueError(f"agents both required and forbidden: {sorted(clash)}")
        if set(self.agents_any_of) and set(self.agents_any_of) <= set(self.agents_forbidden):
            raise ValueError("agents_any_of cannot be satisfied: every option is forbidden")
        if (
            self.min_task_calls is not None
            and self.max_task_calls is not None
            and self.min_task_calls > self.max_task_calls
        ):
            raise ValueError("min_task_calls is greater than max_task_calls")
        return self


class JudgeSpec(_Strict):
    rubric: str = Field(..., pattern=r"^[a-z0-9_-]{1,64}$")
    criteria: str = Field(..., min_length=1)
    min_score: int = Field(default=4, ge=1, le=5)


class FakeMainStep(_Strict):
    """One scripted main-agent response: delegate, answer, or fail.

    ``route`` scripts the routing model's pick of one agent, for scenarios
    whose graph routes without the main agent.
    """

    task: Optional[list[AgentId]] = None
    answer: Optional[str] = None
    error: Optional[str] = Field(default=None, min_length=1)
    route: Optional[AgentId] = Field(default=None, pattern=AGENT_ID_PATTERN)

    @model_validator(mode="after")
    def _one_of(self) -> "FakeMainStep":
        given = [v for v in (self.task, self.answer, self.error, self.route) if v is not None]
        if len(given) != 1:
            raise ValueError("a fake main step needs exactly one of 'task', 'answer', 'error' or 'route'")
        if self.task is not None:
            if not self.task:
                raise ValueError("a fake 'task' step needs at least one agent id")
            _agent_ids(self.task)
        return self


class FakeAgentStep(_Strict):
    """A scripted agent response other than plain text: fail, or call a tool."""

    error: Optional[str] = Field(default=None, min_length=1)
    tool: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @model_validator(mode="after")
    def _one_of(self) -> "FakeAgentStep":
        if (self.error is None) == (self.tool is None):
            raise ValueError("a fake agent step needs exactly one of 'error' or 'tool'")
        return self


class FakeScript(_Strict):
    """Script for the fake backend. Every other backend ignores it.

    Agent steps are plain reply text, ``{error: ...}`` to fail the call, or
    ``{tool: name}`` to call one of the agent's tools.
    """

    main: list[FakeMainStep] = Field(default_factory=list)
    agents: dict[AgentId, list[Union[str, FakeAgentStep]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "FakeScript":
        _agent_ids(list(self.agents))
        return self


class Turn(_Strict):
    user: str = Field(..., min_length=1)
    explicit_agent: Optional[AgentId] = Field(default=None, pattern=AGENT_ID_PATTERN)
    input: Optional[TurnInput] = None
    expect: TurnExpectation = Field(default_factory=TurnExpectation)
    judge: Optional[JudgeSpec] = None
    fake: Optional[FakeScript] = None


class ScenarioLimits(_Strict):
    max_agents: Optional[int] = Field(default=None, ge=1)


class Scenario(_Strict):
    """A single multi-turn conversation and its expectations."""

    schema_version: Literal[1] = Field(..., alias="schema")
    id: str = Field(..., pattern=SCENARIO_ID_PATTERN)
    title: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    pack: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    backends: list[BackendName] = Field(..., min_length=1)
    samples: dict[BackendName, int] = Field(default_factory=dict)
    limits: Optional[ScenarioLimits] = None
    routing: RoutingMode = "hybrid"
    turns: list[Turn] = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _check(self) -> "Scenario":
        if len(set(self.backends)) != len(self.backends):
            raise ValueError("duplicate backend names")
        unknown = set(self.samples) - set(self.backends)
        if unknown:
            raise ValueError(f"samples given for backends not listed in 'backends': {sorted(unknown)}")
        bad_counts = {k: v for k, v in self.samples.items() if v < 1}
        if bad_counts:
            raise ValueError(f"sample counts must be at least 1: {bad_counts}")
        for index, turn in enumerate(self.turns, start=1):
            ref = turn.expect.same_agents_as_turn
            if ref is not None and ref.turn >= index:
                raise ValueError(
                    f"turn {index}: same_agents_as_turn must point at an earlier turn, got {ref.turn}"
                )
            if turn.fake is not None and "fake" not in self.backends:
                raise ValueError(f"turn {index}: has a 'fake' script but 'fake' is not a listed backend")
        return self

    def samples_for(self, backend: BackendName) -> int:
        """Number of runs for ``backend``: one for scripted backends, three otherwise."""
        if backend in self.samples:
            return self.samples[backend]
        return 1 if backend in ("fake", "replay") else 3
