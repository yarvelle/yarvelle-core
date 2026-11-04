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

"""Agent sources feeding the AgentRegistry: pack/workspace files and stored (database) agents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable

from yarvelle_core.constants.paths import SYSTEM_AGENTS_DIR
from yarvelle_core.loaders.agent_loader import load_agent, load_agent_from_record
from yarvelle_core.schemas.manifest import AgentManifest, SkillManifest

logger = logging.getLogger(__name__)

SOURCE_FILE = "file"
SOURCE_DB = "db"

# Stored agent types read by DbAgentSource by default. Bundled and system rows
# are copies of file agents written by startup seeding, so they are skipped.
DEFAULT_DB_AGENT_TYPES: Tuple[str, ...] = ("user",)


@dataclass
class AgentRecord:
    """One validated agent entry produced by a source."""

    manifest: AgentManifest
    effective_tools: List[str]
    skills: List[SkillManifest]
    source: str
    origin: str
    is_system: bool = False


@dataclass
class RejectedAgent:
    """An agent definition a source could not validate (kept out of the catalog)."""

    agent_id: str
    source: str
    origin: str
    reason: str


@dataclass
class SourceResult:
    """Records and rejections from one source load."""

    records: List[AgentRecord] = field(default_factory=list)
    rejected: List[RejectedAgent] = field(default_factory=list)


@runtime_checkable
class AgentSource(Protocol):
    """Port for anything that can supply agent definitions to the registry."""

    kind: str

    def load(self) -> SourceResult:
        """Returns validated records and rejections; must not raise for one bad agent."""
        ...


def _candidate_dirs(agents_dir: Path) -> List[Tuple[Path, bool]]:
    """Lists agent directories under agents_dir (and its _system folder) with a system flag."""
    found: List[Tuple[Path, bool]] = []
    if agents_dir.name == SYSTEM_AGENTS_DIR:
        for entry in sorted(agents_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                found.append((entry, True))
        return found
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == SYSTEM_AGENTS_DIR:
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and not sub.name.startswith((".", "_")):
                    found.append((sub, True))
        elif not entry.name.startswith((".", "_")):
            found.append((entry, False))
    return found


class FilesystemAgentSource:
    """Loads agents from one agents/ directory (pack or workspace), including agents/_system."""

    kind = SOURCE_FILE

    def __init__(self, agents_dir: Union[Path, str], skills_dir: Optional[Union[Path, str]] = None) -> None:
        self.agents_dir = Path(agents_dir).resolve()
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else None

    def load(self) -> SourceResult:
        result = SourceResult()
        if not self.agents_dir.is_dir():
            logger.warning("Agents directory does not exist: %s", self.agents_dir)
            return result
        for entry, is_system in _candidate_dirs(self.agents_dir):
            try:
                manifest, effective_tools, skills = load_agent(entry, self.skills_dir)
            except Exception as err:  # one bad agent must not hide the others
                logger.warning("Failed to load agent %s: %s", entry.name, err)
                result.rejected.append(RejectedAgent(entry.name, self.kind, str(entry), str(err)))
                continue
            if is_system:
                manifest.hidden = True
            result.records.append(
                AgentRecord(manifest, effective_tools, skills, self.kind, str(entry), is_system)
            )
        return result

    def __repr__(self) -> str:
        return f"FilesystemAgentSource({self.agents_dir})"


def _json_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _persona_value(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, dict):
            return parsed
    return value


def agent_row_to_record(row: Any) -> Dict[str, Any]:
    """Maps a stored agent row (ORM object or mapping) to AgentManifest fields."""

    def get(name: str, default: Any = None) -> Any:
        if isinstance(row, Mapping):
            return row.get(name, default)
        return getattr(row, name, default)

    record: Dict[str, Any] = {
        "id": get("id"),
        "title": get("title"),
        "description": get("description") or "",
        "persona": _persona_value(get("persona") or ""),
        "model": get("model") or None,
        "domain": get("domain") or None,
        "category": get("category"),
        "risk_class": get("risk_class") or None,
        "icon": get("icon") or None,
        "maturity": get("maturity") or None,
        "can_delegate": get("can_delegate"),
        "max_iterations": get("max_iterations"),
        "hidden": get("hidden"),
    }
    for field_name, column in (
        ("skills", "skills_json"),
        ("tools", "tools_json"),
        ("tags", "tags_json"),
        ("care_stages", "care_stages_json"),
        ("target_audience", "target_audience_json"),
        ("forbidden", "forbidden_json"),
    ):
        raw = get(field_name)
        record[field_name] = _json_list(raw if raw is not None else get(column))
    return record


class DbAgentSource:
    """Supplies stored agents (for example API-created ones) from a snapshot of rows.

    The registry loads synchronously, so rows are fetched separately (see
    :func:`fetch_db_agent_rows`) and handed in with :meth:`set_rows`.
    """

    kind = SOURCE_DB

    def __init__(
        self,
        rows: Optional[Iterable[Any]] = None,
        skills_dir: Optional[Union[Path, str]] = None,
        types: Sequence[str] = DEFAULT_DB_AGENT_TYPES,
    ) -> None:
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else None
        self.types = tuple(types)
        self._rows: List[Any] = list(rows or [])

    def set_rows(self, rows: Iterable[Any]) -> None:
        self._rows = list(rows)

    def _type_of(self, row: Any) -> Optional[str]:
        return row.get("type") if isinstance(row, Mapping) else getattr(row, "type", None)

    def load(self) -> SourceResult:
        result = SourceResult()
        for row in self._rows:
            row_type = self._type_of(row)
            if self.types and row_type is not None and row_type not in self.types:
                continue
            record = agent_row_to_record(row)
            agent_id = str(record.get("id") or "")
            origin = f"db:{agent_id}"
            try:
                manifest, effective_tools, skills = load_agent_from_record(record, self.skills_dir)
            except Exception as err:
                logger.warning("Stored agent %r rejected: %s", agent_id, err)
                result.rejected.append(RejectedAgent(agent_id, self.kind, origin, str(err)))
                continue
            result.records.append(AgentRecord(manifest, effective_tools, skills, self.kind, origin))
        return result

    def __repr__(self) -> str:
        return f"DbAgentSource(rows={len(self._rows)}, types={self.types})"


async def fetch_db_agent_rows(session: Any, types: Sequence[str] = DEFAULT_DB_AGENT_TYPES) -> List[Any]:
    """Reads stored agent rows of the given types with an AsyncSession."""
    from sqlalchemy import select

    from yarvelle_core.db.models import Agent

    stmt = select(Agent)
    if types:
        stmt = stmt.where(Agent.type.in_(list(types)))
    res = await session.execute(stmt.order_by(Agent.id))
    return list(res.scalars().all())


__all__ = [
    "DEFAULT_DB_AGENT_TYPES",
    "SOURCE_DB",
    "SOURCE_FILE",
    "AgentRecord",
    "AgentSource",
    "DbAgentSource",
    "FilesystemAgentSource",
    "RejectedAgent",
    "SourceResult",
    "agent_row_to_record",
    "fetch_db_agent_rows",
]
