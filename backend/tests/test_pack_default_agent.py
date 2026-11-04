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

"""Core takes its default agent from pack config and has none of its own."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import sqlalchemy as sa
from alembic import command

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.db.session import get_alembic_config
from yarvelle_core.engine.service import AgentExecutionService
from yarvelle_core.loaders.agent_loader import load_agent
from yarvelle_core.pack import collect_routing_hints, resolve_default_agent
from yarvelle_core.pack.spec import PackSpec
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec
from yarvelle_core.workflows.nodes.orchestrator_node import OrchestratorNode


def _pack(pack_id: str, default_agent: str | None = None) -> PackSpec:
    return PackSpec(
        id=pack_id,
        name=f"{pack_id.title()} Pack",
        version="0.1.0",
        domain=pack_id,
        requires_core=">=0.1.0",
        owned_scopes=[f"{pack_id}.records"],
        risk_tier_max="T1",
        orchestration=PackOrchestrationSpec(default_agent=default_agent) if default_agent else None,
    )


# ------------------------------------------------------------------ pack routing


def test_routing_hints_never_invent_an_agent_id() -> None:
    assert collect_routing_hints([_pack("finance")]) == []


def test_routing_hints_use_pack_default_agent() -> None:
    hints = collect_routing_hints([_pack("finance", "budget-planner")])
    assert len(hints) == 1
    assert hints[0].default_agent == "budget-planner"
    assert hints[0].domain == "finance"


def test_resolve_default_agent() -> None:
    assert resolve_default_agent([]) is None
    assert resolve_default_agent([_pack("finance")]) is None
    assert resolve_default_agent([_pack("finance", "budget-planner"), _pack("travel")]) == "budget-planner"
    assert resolve_default_agent([_pack("finance", "budget-planner"), _pack("travel", "budget-planner")]) == "budget-planner"
    with pytest.raises(ValueError, match="conflicting"):
        resolve_default_agent([_pack("finance", "budget-planner"), _pack("travel", "trip-organizer")])


# ------------------------------------------------------------------ orchestrator


def _empty_registry(tmp_path: Path) -> AgentRegistry:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    return AgentRegistry(agents_dir=agents_dir)


def _state(prompt: str) -> Dict[str, Any]:
    return {"messages": [{"role": "user", "content": prompt}]}


@pytest.mark.asyncio
async def test_orchestrator_without_default_returns_error(tmp_path: Path) -> None:
    node = OrchestratorNode(model=None, registry=_empty_registry(tmp_path))
    result = await node.execute(_state("plan my week"))
    assert result.get("next_step") == "error"
    assert "orchestration.default_agent" in result.get("error", "")


@pytest.mark.asyncio
async def test_orchestrator_falls_back_to_pack_default(tmp_path: Path) -> None:
    node = OrchestratorNode(model=None, registry=_empty_registry(tmp_path), default_agent="budget-planner")
    result = await node.execute(_state("plan my week"))
    assert result.get("next_step") != "error"
    assert result.get("current_agent") == "budget-planner"


# ------------------------------------------------------------------ execution service


async def _collect(service: AgentExecutionService, **kwargs: Any) -> List[Dict[str, Any]]:
    return [event async for event in service.execute_turn(**kwargs)]


@pytest.mark.asyncio
async def test_execute_turn_without_agent_or_default_errors(tmp_path: Path) -> None:
    service = AgentExecutionService(model=None, graph=None, workspace_root=tmp_path)
    events = await _collect(service, thread_id="t-none", prompt="hello")
    assert events and events[0]["type"] == "error"
    assert "orchestration.default_agent" in events[0]["message"]


@pytest.mark.asyncio
async def test_execute_turn_unknown_agent_errors(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    service = AgentExecutionService(model=None, graph=None, workspace_root=tmp_path, default_agent_id="budget-planner")
    events = await _collect(service, thread_id="t-unknown", prompt="hello")
    assert events and events[0]["type"] == "error"
    assert "budget-planner" in events[0]["message"]


# ------------------------------------------------------------------ extensions


def test_metadata_extensions_merge_into_manifest(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agents" / "budget-planner"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.yaml").write_text(
        "id: budget-planner\ntitle: Budget Planner\npersona: You plan budgets.\nextensions:\n  tier: gold\n", encoding="utf-8"
    )
    (agent_dir / "metadata.yaml").write_text(
        "extensions:\n  tier: silver\n  stages: [plan, review]\n", encoding="utf-8"
    )
    agent, _, _ = load_agent(agent_dir, None)
    assert agent.extensions == {"tier": "gold", "stages": ["plan", "review"]}
    assert not hasattr(agent, "care_stages")


def test_migration_moves_care_stages_into_extensions(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        cfg = get_alembic_config(conn)
        command.upgrade(cfg, "0011_scopes")
        cols = {c["name"] for c in sa.inspect(conn).get_columns("agent")}
        assert "care_stages_json" in cols
        base = {c: "[]" for c in cols if c.endswith("_json")}
        rows = [("a-one", '["plan", "review"]'), ("a-two", "[]")]
        for agent_id, stages in rows:
            values = {
                **base,
                "id": agent_id,
                "type": "custom",
                "title": agent_id,
                "description": "",
                "persona": "",
                "model": "stub",
                "domain": "general",
                "category": "general",
                "risk_class": "admin",
                "icon": "Bot",
                "maturity": "stable",
                "can_delegate": False,
                "max_iterations": 3,
                "hidden": False,
                "is_public": False,
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
                "care_stages_json": stages,
            }
            values = {k: v for k, v in values.items() if k in cols}
            names = ", ".join(values)
            params = ", ".join(f":{k}" for k in values)
            conn.execute(sa.text(f"INSERT INTO agent ({names}) VALUES ({params})"), values)

        command.upgrade(cfg, "0012_agent_extensions")
        cols = {c["name"] for c in sa.inspect(conn).get_columns("agent")}
        assert "care_stages_json" not in cols and "extensions_json" in cols
        got = dict(conn.execute(sa.text("SELECT id, extensions_json FROM agent ORDER BY id")).fetchall())
        assert json.loads(got["a-one"]) == {"care_stages": ["plan", "review"]}
        assert json.loads(got["a-two"]) == {}

        command.downgrade(cfg, "0011_scopes")
        got = dict(conn.execute(sa.text("SELECT id, care_stages_json FROM agent ORDER BY id")).fetchall())
        assert json.loads(got["a-one"]) == ["plan", "review"]
        assert json.loads(got["a-two"]) == []
    engine.dispose()
