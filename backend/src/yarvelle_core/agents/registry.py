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

"""AgentRegistry: one catalog of agents from pack files and stored agents, keyed by id.

Sources (ADR-0005, 2026-11-03 amendment; plan step C2):

* :class:`~yarvelle_core.agents.sources.FilesystemAgentSource` for pack or
  workspace ``agents/`` directories (including ``agents/_system``), and
* :class:`~yarvelle_core.agents.sources.DbAgentSource` for stored agents.

Merge rules are deterministic: two file agents (or two stored agents) with the
same id fail the load with :class:`DuplicateAgentError`; a stored agent whose id
matches a file agent is ignored and recorded in :attr:`AgentRegistry.conflicts`.
Unknown ids raise :class:`AgentNotFoundError`; nothing is substituted. There
are no id aliases.

The registry also builds Deep Agents subagent specs. Every spec carries the
required policy and audit hooks from :mod:`yarvelle_core.agents.subagent_hooks`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from yarvelle_core.agents.errors import AgentNotFoundError, DuplicateAgentError
from yarvelle_core.agents.sources import (
    SOURCE_DB,
    AgentRecord,
    AgentSource,
    DbAgentSource,
    FilesystemAgentSource,
    RejectedAgent,
    fetch_db_agent_rows,
)
from yarvelle_core.agents.subagent_hooks import ensure_subagent_hooks, required_subagent_middleware
from yarvelle_core.config import settings
from yarvelle_core.constants.agents import AGENT_ORCHESTRATOR
from yarvelle_core.schemas.manifest import SLUG_REGEX, AgentManifest, AgentPersonaObject, SkillManifest

logger = logging.getLogger(__name__)

ToolResolver = Callable[[AgentManifest, List[str]], List[Any]]
MiddlewareFactory = Callable[[AgentManifest], Sequence[Any]]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AgentConflict:
    """A stored agent ignored because a file agent already uses its id."""

    agent_id: str
    kept_source: str
    kept_origin: str
    ignored_source: str
    ignored_origin: str


def _extract_first_line(persona: Union[str, AgentPersonaObject, Dict[str, Any], None]) -> str:
    """Extracts the first non-empty, non-header line from an agent persona."""
    if not persona:
        return ""
    if isinstance(persona, str):
        for line in persona.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        return ""
    if isinstance(persona, AgentPersonaObject):
        if persona.role:
            return persona.role.strip()
        if persona.instructions:
            for line in persona.instructions.strip().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        return ""
    if isinstance(persona, dict):
        if persona.get("role"):
            return str(persona["role"]).strip()
        if persona.get("instructions"):
            for line in str(persona["instructions"]).strip().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return ""


def _system_prompt(persona: Union[str, AgentPersonaObject, Dict[str, Any], None]) -> str:
    """Flattens a persona (markdown string or role/tone/instructions object) into a system prompt."""
    if not persona:
        return ""
    if isinstance(persona, str):
        return persona.strip()
    if isinstance(persona, dict):
        persona = AgentPersonaObject(**{k: persona.get(k) for k in ("role", "tone", "instructions")})
    parts = [persona.role, f"Tone: {persona.tone}" if persona.tone else None, persona.instructions]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _model_string(model: Any) -> Optional[str]:
    if not model:
        return None
    if isinstance(model, str):
        return model
    name = getattr(model, "name", None)
    provider = getattr(model, "provider", None)
    if not name:
        return None
    return f"{provider}:{name}" if provider else str(name)


def _tool_definitions(_manifest: AgentManifest, tool_names: List[str]) -> List[Any]:
    from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS

    return [CLOSED_TOOL_DEFINITIONS[t] for t in tool_names if t in CLOSED_TOOL_DEFINITIONS]


class AgentRegistry:
    """Catalog of validated agents keyed by id, merged from file and stored sources."""

    def __init__(
        self,
        agents_dir: Optional[Union[Path, str]] = None,
        skills_dir: Optional[Union[Path, str]] = None,
        *,
        sources: Optional[Sequence[AgentSource]] = None,
        db_source: Optional[DbAgentSource] = None,
        tool_resolver: Optional[ToolResolver] = None,
        middleware_factory: Optional[MiddlewareFactory] = None,
    ) -> None:
        self._agents_dir = Path(agents_dir).resolve() if agents_dir else None
        self._skills_dir = Path(skills_dir).resolve() if skills_dir else None
        file_sources: List[AgentSource] = []
        if self._agents_dir is not None:
            file_sources.append(FilesystemAgentSource(self._agents_dir, self._skills_dir))
        file_sources.extend(sources or [])
        self._sources: List[AgentSource] = file_sources
        self._db_source = db_source
        self._tool_resolver = tool_resolver
        self._middleware_factory = middleware_factory
        self._agents: Dict[str, AgentManifest] = {}
        self._effective_tools: Dict[str, List[str]] = {}
        self._loaded_skills: Dict[str, List[SkillManifest]] = {}
        self._records: Dict[str, AgentRecord] = {}
        self.conflicts: List[AgentConflict] = []
        self.rejected: List[RejectedAgent] = []
        self.version = 0
        self.reload()

    # ------------------------------------------------------------------ loading

    @property
    def sources(self) -> List[AgentSource]:
        """Configured sources in precedence order (file sources first, then the stored source)."""
        return [*self._sources, *([self._db_source] if self._db_source is not None else [])]

    def reload(self) -> None:
        """Rebuilds the catalog from every source and bumps :attr:`version`.

        Raises DuplicateAgentError when two agents of the same source kind share an id.
        """
        records: Dict[str, AgentRecord] = {}
        conflicts: List[AgentConflict] = []
        rejected: List[RejectedAgent] = []

        for source in self.sources:
            result = source.load()
            rejected.extend(result.rejected)
            seen_here: Dict[str, AgentRecord] = {}
            for rec in result.records:
                aid = rec.manifest.id
                if aid in seen_here:
                    raise DuplicateAgentError(aid, [seen_here[aid].origin, rec.origin])
                seen_here[aid] = rec
                existing = records.get(aid)
                if existing is None:
                    records[aid] = rec
                    continue
                if existing.source == rec.source:
                    raise DuplicateAgentError(aid, [existing.origin, rec.origin])
                conflict = AgentConflict(aid, existing.source, existing.origin, rec.source, rec.origin)
                conflicts.append(conflict)
                logger.warning(
                    "Agent id %r from %s ignored; %s already defines it (%s wins)",
                    aid, rec.origin, existing.origin, existing.source,
                )

        self._records = records
        self._agents = {aid: r.manifest for aid, r in records.items()}
        self._effective_tools = {aid: list(r.effective_tools) for aid, r in records.items()}
        self._loaded_skills = {aid: list(r.skills) for aid, r in records.items()}
        self.conflicts = conflicts
        self.rejected = rejected
        self.version += 1

    def set_db_rows(self, rows: Sequence[Any]) -> None:
        """Replaces the stored-agent snapshot and reloads the catalog."""
        if self._db_source is None:
            self._db_source = DbAgentSource(skills_dir=self._skills_dir)
        self._db_source.set_rows(rows)
        self.reload()

    async def refresh_from_db(self, session: Any) -> None:
        """Fetches stored agents with ``session`` and reloads the catalog."""
        types = self._db_source.types if self._db_source is not None else None
        rows = await (fetch_db_agent_rows(session, types) if types is not None else fetch_db_agent_rows(session))
        self.set_db_rows(rows)

    # ---------------------------------------------------------------- lookups

    def get(self, agent_id: str) -> Optional[AgentManifest]:
        """Returns the catalog entry for ``agent_id`` or None. Never loads or substitutes."""
        if not isinstance(agent_id, str) or not agent_id:
            return None
        return self._agents.get(agent_id)

    def resolve(self, agent_id: str) -> AgentManifest:
        """Returns the catalog entry for ``agent_id`` or raises AgentNotFoundError."""
        manifest = self.get(agent_id)
        if manifest is None:
            raise AgentNotFoundError(agent_id, self._agents.keys())
        return manifest

    def __getitem__(self, agent_id: str) -> AgentManifest:
        return self.resolve(agent_id)

    def __contains__(self, agent_id: object) -> bool:
        return isinstance(agent_id, str) and agent_id in self._agents

    def __len__(self) -> int:
        return len(self._agents)

    def has_agent(self, agent_id: str) -> bool:
        return agent_id in self

    def source_of(self, agent_id: str) -> str:
        """Returns the source kind ('file' or 'db') of a registered agent."""
        self.resolve(agent_id)
        return self._records[agent_id].source

    def list_agents(self) -> List[AgentManifest]:
        """Returns all registered AgentManifests sorted by id."""
        return [self._agents[aid] for aid in sorted(self._agents)]

    def list_agent_ids(self) -> List[str]:
        return sorted(self._agents)

    def get_effective_tools(self, agent_id: str) -> List[str]:
        """Returns the effective tool allowlist for a registered agent ([] if unknown)."""
        return list(self._effective_tools.get(agent_id, []))

    def get_loaded_skills(self, agent_id: str) -> List[SkillManifest]:
        """Returns loaded skills for a registered agent ([] if unknown)."""
        return list(self._loaded_skills.get(agent_id, []))

    def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        """Returns a loaded SkillManifest by id, or loads it from skills_dir."""
        for skills in self._loaded_skills.values():
            for sk in skills:
                if sk.id == skill_id:
                    return sk
        if self._skills_dir and SLUG_REGEX.match(skill_id or "") and (self._skills_dir / skill_id).is_dir():
            from yarvelle_core.loaders.skill_loader import load_skill

            try:
                return load_skill(self._skills_dir / skill_id)
            except Exception:
                return None
        return None

    @property
    def effective_tools_map(self) -> Dict[str, List[str]]:
        return dict(self._effective_tools)

    def get_delegatable_agents(self, exclude: str = "") -> List[AgentManifest]:
        """Returns agents that can be handed work (not hidden, not delegators, not ``exclude``)."""
        return [
            a for a in self.list_agents()
            if a.id != exclude and not a.can_delegate and not a.hidden
        ]

    def search(self, query: str = "", limit: Optional[int] = None, exclude: str = AGENT_ORCHESTRATOR) -> List[AgentManifest]:
        """Keyword search over delegatable agents (id, title, description, tags, category, skills).

        An empty query returns every delegatable agent. Results are ordered by the
        number of matching query terms, then by id.
        """
        agents = self.get_delegatable_agents(exclude)
        terms = set(_TOKEN_RE.findall((query or "").lower()))
        if terms:
            scored = []
            for a in agents:
                hay = " ".join(
                    [a.id, a.title, a.description or _extract_first_line(a.persona), a.category, *a.tags, *a.skills]
                ).lower()
                words = set(_TOKEN_RE.findall(hay))
                score = len(terms & words)
                if score:
                    scored.append((-score, a.id, a))
            agents = [a for _, _, a in sorted(scored, key=lambda t: (t[0], t[1]))]
        return agents[:limit] if limit else agents

    def format_agent_catalog(
        self,
        exclude: str = AGENT_ORCHESTRATOR,
        agents: Optional[Sequence[AgentManifest]] = None,
    ) -> str:
        """Formats agents as markdown lines for a model prompt or the list_agents tool."""
        chosen = list(agents) if agents is not None else self.get_delegatable_agents(exclude)
        lines: List[str] = []
        for a in chosen:
            desc = a.description or _extract_first_line(a.persona)
            tools_str = ", ".join(self._effective_tools.get(a.id, []))
            lines.append(f"- **{a.id}** ({a.title}): {desc}\n  Tools: [{tools_str}]")
        return "\n".join(lines)

    # ------------------------------------------------------------- subagents

    def get_subagent(self, agent_id: str, resolve_tools: bool = False) -> Dict[str, Any]:
        """Builds a Deep Agents ``SubAgent`` spec for a registered agent.

        Keys: ``name`` (agent id), ``description``, ``system_prompt``, ``tools``,
        ``middleware`` (required hooks first, then any factory extras) and
        ``model`` when the agent declares one (otherwise the main agent's model
        is inherited). ``tools`` are the effective tool names, or resolved tools
        when ``resolve_tools`` is set or a ``tool_resolver`` was configured.

        Raises AgentNotFoundError for an unknown id and SubagentHookError if a
        required hook is missing.
        """
        manifest = self.resolve(agent_id)
        tool_names = self.get_effective_tools(agent_id)
        if self._tool_resolver is not None:
            tools: List[Any] = list(self._tool_resolver(manifest, tool_names))
        elif resolve_tools:
            tools = _tool_definitions(manifest, tool_names)
        else:
            tools = list(tool_names)

        middleware: List[Any] = required_subagent_middleware(manifest.id)
        if self._middleware_factory is not None:
            middleware.extend(self._middleware_factory(manifest))

        spec: Dict[str, Any] = {
            "name": manifest.id,
            "description": manifest.description or _extract_first_line(manifest.persona) or manifest.title,
            "system_prompt": _system_prompt(manifest.persona),
            "tools": tools,
            "middleware": middleware,
        }
        model = _model_string(manifest.model)
        if model:
            spec["model"] = model
        return ensure_subagent_hooks(spec)

    def list_subagents(self, resolve_tools: bool = False) -> List[Dict[str, Any]]:
        """Returns subagent specs for every delegatable (visible, non-delegating) agent."""
        return [
            self.get_subagent(a.id, resolve_tools=resolve_tools)
            for a in self.get_delegatable_agents(exclude="")
        ]


_registry_instance: Optional[AgentRegistry] = None


def get_agent_registry(
    agents_dir: Optional[Union[Path, str]] = None,
    skills_dir: Optional[Union[Path, str]] = None,
    force_reload: bool = False,
) -> AgentRegistry:
    """Returns the process-wide AgentRegistry, rebuilding it when the agents dir changes."""
    global _registry_instance
    target_agents_dir = Path(agents_dir).resolve() if agents_dir else settings.get_agents_dir().resolve()
    target_skills_dir = Path(skills_dir).resolve() if skills_dir else settings.get_skills_dir().resolve()
    if (
        _registry_instance is None
        or force_reload
        or agents_dir is not None
        or _registry_instance._agents_dir != target_agents_dir
    ):
        _registry_instance = AgentRegistry(target_agents_dir, target_skills_dir)
    return _registry_instance


__all__ = [
    "AgentConflict",
    "AgentNotFoundError",
    "AgentRegistry",
    "DuplicateAgentError",
    "_extract_first_line",
    "get_agent_registry",
]
