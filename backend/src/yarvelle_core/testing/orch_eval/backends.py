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

"""Backend interface for the orchestration eval harness.

A backend supplies the chat models for one run: the main agent, each
subagent and the judge. The concrete backends (scripted fake, cassette
replay, local Ollama and metered providers) plug in behind this interface.
Provider SDKs must be imported lazily inside a backend, so importing this
module never touches the network or a key.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal, Protocol, runtime_checkable

from yarvelle_core.testing.orch_eval.schema import AGENT_ID_PATTERN, BackendName

BACKEND_NAMES: tuple[BackendName, ...] = ("fake", "replay", "ollama", "provider")

# Backends that never spend money.
FREE_BACKENDS: frozenset[str] = frozenset({"fake", "replay", "ollama"})

_AGENT_ROLE_RE = re.compile(r"^agent:(" + AGENT_ID_PATTERN.strip("^$") + r")$")


@dataclass(frozen=True)
class CostTable:
    """US dollars per million tokens."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    def __post_init__(self) -> None:
        if self.input_per_mtok < 0 or self.output_per_mtok < 0:
            raise ValueError("token prices cannot be negative")

    @property
    def is_free(self) -> bool:
        return self.input_per_mtok == 0 and self.output_per_mtok == 0

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / 1_000_000


FREE = CostTable()


@dataclass(frozen=True)
class Role:
    """Which model a backend is asked for."""

    kind: Literal["main", "agent", "judge"]
    agent_id: str | None = None

    def __str__(self) -> str:
        return f"agent:{self.agent_id}" if self.kind == "agent" else self.kind


def parse_role(value: str) -> Role:
    """Parses ``"main"``, ``"judge"`` or ``"agent:<id>"``."""
    if value in ("main", "judge"):
        return Role(kind=value)  # type: ignore[arg-type]
    match = _AGENT_ROLE_RE.match(value)
    if match:
        return Role(kind="agent", agent_id=match.group(1))
    raise ValueError(f"unknown model role {value!r}; expected 'main', 'judge' or 'agent:<id>'")


@runtime_checkable
class EvalBackend(Protocol):
    """Supplies chat models for one eval run."""

    name: str
    cost_per_mtok: CostTable

    def model_for(self, role: Role) -> Any:
        """Returns a LangChain chat model for ``role``."""
        ...

    def describe(self) -> dict[str, Any]:
        """Provider, model, version or digest, seed and temperature. Never keys."""
        ...
