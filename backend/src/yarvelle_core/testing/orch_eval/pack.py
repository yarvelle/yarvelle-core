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

"""Eval packs: the agents and routing config a scenario runs against.

An eval pack is a directory with a ``pack.yaml`` and an ``agents/`` folder in
the normal agent layout (``agents/<id>/agent.yaml`` plus a persona). It is
loaded through the real :class:`AgentRegistry`, so a pack that the runtime
would reject fails here too. Tools listed under ``offline_tools`` are
replaced by local no-op tools that return a fixed string.

``guardrail_flags`` maps a flag name to the words that raise it. The harness
turns it into a safety policy whose ``check_flags`` the input guardrail calls,
so flag-triggered fixed routes run from the user's text, as in production.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yarvelle_core.engine.safety_policy import NeutralSafetyPolicy
from yarvelle_core.schemas.orchestration import GuardrailFlagTrigger, PackOrchestrationSpec

PACK_FILE = "pack.yaml"
AGENTS_DIR = "agents"

_TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class EvalPackError(ValueError):
    """An eval pack could not be loaded."""


class _PackFile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(..., alias="schema")
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str = ""
    orchestration: PackOrchestrationSpec
    offline_tools: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Agent id -> tool names served by local no-op tools.",
    )
    guardrail_flags: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Flag name -> words that raise it (case-insensitive, whole words).",
    )


class KeywordFlagPolicy(NeutralSafetyPolicy):
    """Harness safety policy: refuses nothing and raises flags on listed words."""

    def __init__(self, words: Mapping[str, Sequence[str]]) -> None:
        self._patterns = {
            flag: [re.compile(rf"(?<!\w){re.escape(w)}(?!\w)", re.IGNORECASE) for w in ws]
            for flag, ws in words.items()
        }

    def check_flags(self, text: Optional[str], ctx: Any = None) -> List[str]:
        body = text or ""
        return [flag for flag, patterns in self._patterns.items() if any(p.search(body) for p in patterns)]


@dataclass(frozen=True)
class PackAgent:
    id: str
    title: str
    hidden: bool
    max_iterations: int


@dataclass(frozen=True)
class EvalPack:
    """A loaded eval pack."""

    id: str
    root: Path
    spec: PackOrchestrationSpec
    registry: Any
    agents: Dict[str, PackAgent] = field(default_factory=dict)
    flag_words: Dict[str, List[str]] = field(default_factory=dict)

    def safety_policy(self) -> KeywordFlagPolicy:
        """The input guardrail policy for this pack (raises ``guardrail_flags``)."""
        return KeywordFlagPolicy(self.flag_words)

    def graph_nodes(self) -> Dict[str, Any]:
        """Graph nodes this pack replaces, by node name (none by default).

        A pack that swaps nodes in production with ``GraphBuilder.with_node``
        (for example its own refusal node) overrides this to return the same
        nodes, so evals run the graph its users get. Names must be in
        :data:`yarvelle_core.engine.builder.OVERRIDABLE_NODES`. The driver calls
        this for every graph it builds, so return new node instances.
        """
        return {}

    def main_agent_reminder(self) -> Optional[Any]:
        """Python reminder hook for the main agent (none by default).

        A pack that passes ``main_agent_reminder`` to ``GraphBuilder`` in
        production returns the same hook here. A ``pack.yaml``
        ``orchestration.delegation.reminder`` applies without this.
        """
        return None

    def flags_for(self, text: str) -> List[str]:
        """Flags the pack's policy raises for ``text``."""
        return self.safety_policy().check_flags(text)

    @property
    def agent_ids(self) -> List[str]:
        return sorted(self.agents)

    @property
    def visible_ids(self) -> List[str]:
        return sorted(a for a, info in self.agents.items() if not info.hidden)

    @property
    def hidden_ids(self) -> List[str]:
        return sorted(a for a, info in self.agents.items() if info.hidden)

    @property
    def route_ids(self) -> List[str]:
        return [r.route_id for r in self.spec.fixed_routes]

    @property
    def route_flags(self) -> List[str]:
        return [r.when.flag for r in self.spec.fixed_routes if isinstance(r.when, GuardrailFlagTrigger)]

    def title(self, agent_id: str) -> str:
        info = self.agents.get(agent_id)
        return info.title if info is not None else agent_id


def _offline_tool(name: str) -> Any:
    from langchain_core.tools import StructuredTool

    def _run(query: str = "") -> str:
        return f"{name}: nothing found for this request."

    return StructuredTool.from_function(
        func=_run,
        name=name,
        description=f"Offline stand-in for the {name} tool. Always returns a fixed note.",
    )


def load_eval_pack(path: Union[str, Path]) -> EvalPack:
    """Loads the eval pack at ``path`` (a directory or its ``pack.yaml``)."""
    from yarvelle_core.agents import AgentRegistry

    root = Path(path)
    if root.is_file():
        root = root.parent
    pack_file = root / PACK_FILE
    if not pack_file.is_file():
        raise EvalPackError(f"{root}: no {PACK_FILE}")
    try:
        data = yaml.safe_load(pack_file.read_text(encoding="utf-8"))
        parsed = _PackFile.model_validate(data)
    except (yaml.YAMLError, ValidationError) as err:
        raise EvalPackError(f"{pack_file}: {err}") from err

    tools: Dict[str, List[Any]] = {}
    for agent_id, names in parsed.offline_tools.items():
        bad = [n for n in names if not re.match(_TOOL_NAME_PATTERN, n)]
        if bad:
            raise EvalPackError(f"{pack_file}: invalid offline tool name(s) {bad} for {agent_id}")
        tools[agent_id] = [_offline_tool(n) for n in names]

    def _resolver(manifest: Any, names: Sequence[str]) -> List[Any]:
        return list(tools.get(manifest.id, []))

    agents_dir = root / AGENTS_DIR
    if not agents_dir.is_dir():
        raise EvalPackError(f"{root}: no {AGENTS_DIR}/ directory")
    try:
        registry = AgentRegistry(agents_dir=agents_dir, tool_resolver=_resolver)
    except Exception as err:  # duplicate ids and similar load failures
        raise EvalPackError(f"{agents_dir}: {err}") from err
    if registry.rejected:
        raise EvalPackError(f"{agents_dir}: rejected agents: {registry.rejected}")

    agents = {
        m.id: PackAgent(id=m.id, title=m.title, hidden=bool(m.hidden), max_iterations=int(m.max_iterations))
        for m in registry.list_agents()
    }
    missing = [a for a in parsed.orchestration.referenced_agent_ids() if a not in agents]
    unknown_tools = [a for a in parsed.offline_tools if a not in agents]
    bad_flags = [f for f in parsed.guardrail_flags if not re.match(r"^[a-z0-9_-]{1,64}$", f)]
    empty_flags = [f for f, words in parsed.guardrail_flags.items() if not [w for w in words if w.strip()]]
    route_flags = [
        r.when.flag for r in parsed.orchestration.fixed_routes if isinstance(r.when, GuardrailFlagTrigger)
    ]
    undeclared = [f for f in route_flags if f not in parsed.guardrail_flags]
    if bad_flags:
        raise EvalPackError(f"{pack_file}: invalid guardrail flag name(s) {bad_flags}")
    if empty_flags:
        raise EvalPackError(f"{pack_file}: guardrail flag(s) {empty_flags} list no words")
    if undeclared:
        raise EvalPackError(f"{pack_file}: fixed routes use flag(s) {undeclared} not listed under guardrail_flags")
    if missing:
        raise EvalPackError(f"{pack_file}: orchestration names unknown agent(s) {missing}")
    if unknown_tools:
        raise EvalPackError(f"{pack_file}: offline_tools names unknown agent(s) {unknown_tools}")
    return EvalPack(
        id=parsed.id,
        root=root,
        spec=parsed.orchestration,
        registry=registry,
        agents=agents,
        flag_words={f: [w.strip() for w in words if w.strip()] for f, words in parsed.guardrail_flags.items()},
    )


def find_pack_dir(start: Union[str, Path], pack_id: str) -> Optional[Path]:
    """Finds the pack ``pack_id`` near a scenario file.

    Walks up from ``start`` and looks for ``pack/pack.yaml`` or
    ``packs/<pack_id>/pack.yaml`` whose ``id`` is ``pack_id``.
    """
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for parent in (here, *here.parents):
        for candidate in (parent / "pack", parent / "packs" / pack_id):
            pack_file = candidate / PACK_FILE
            if not pack_file.is_file():
                continue
            try:
                data = yaml.safe_load(pack_file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("id") == pack_id:
                return candidate
    return None


__all__ = ["EvalPack", "EvalPackError", "KeywordFlagPolicy", "PackAgent", "find_pack_dir", "load_eval_pack"]
