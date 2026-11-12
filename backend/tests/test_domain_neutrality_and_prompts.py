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

"""Contract and regression tests for Issue #52:
- Handlebars prompt extraction and pack override resolution
- Domain neutrality across core modules, errors.yaml, and ALLOWLIST governance
- Prefixed yarvelle_core.connectors imports and built-in tool handler smoke checks
- Fail-closed Gmail MCP delegation (no fabricated success responses)
- Idempotent Alembic migration 0014_neutralize_profile_columns
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Dict, List
import yaml

from alembic import command
import pytest
import sqlalchemy as sa

import yarvelle_core
from yarvelle_core.connectors.errors import ConnectorNotConfiguredError
from yarvelle_core.db.session import get_alembic_config
from yarvelle_core.engine.tool_exec import (
    TaintFlag,
    ToolContext,
    UntrustedResult,
    execute_tool_call,
)
from yarvelle_core.engine.tool_registry import create_default_registry
from yarvelle_core.middleware.skills import compose_skills_system_prompt
from yarvelle_core.resources.loader import ResourceLoader, get_resource_loader
from yarvelle_core.resources.pack_resolver import PackResourceResolver
from yarvelle_core.tools.db_query_planner import compose_query_planner_prompt
from yarvelle_core.workflows.nodes.orchestrator_node import compose_tier1_classifier_prompt


def _load_neutral_scan_module() -> Any:
    scan_path = Path(__file__).resolve().parent / "test_neutral_words_scan.py"
    spec = importlib.util.spec_from_file_location("_neutral_words_scan_mod", scan_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


neutral_scan = _load_neutral_scan_module()


EXTRACTED_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "skills_middleware": {
        "skills_list": "- budget-planner: Plan household budgets (`/skills/budget-planner/SKILL.md`)",
        "additional_guidelines": "Always cite uploaded budget spreadsheets when referenced.",
    },
    "main_agent_coordinator": {
        "delegation_section": "specialist_agents:\n  - planner: Organizes project milestones",
        "synthesis_guidelines": "Combine specialist findings concisely.",
    },
    "db_query_planner": {
        "profile_id": "prof-123",
        "allowed_tables_csv": "notes, reminders",
        "schema_text": "notes(id, profile_id, title)\nreminders(id, profile_id, title)",
    },
    "tier1_domain_classifier": {
        "has_attachments": True,
        "agents_block": "- planner: Task planning specialist (domain: operations)",
    },
    "deliberation_propose": {
        "agent_title": "Operations Planner",
        "agent_id": "ops-planner",
        "domain": "operations",
        "persona_summary": "Structured project planning specialist.",
        "topic": "Quarterly household maintenance schedule",
    },
    "deliberation_critique": {
        "reviewer_title": "Risk Reviewer",
        "reviewer_id": "risk-reviewer",
        "domain": "operations",
        "topic": "Quarterly household maintenance schedule",
        "proposals_block": "### Proposal from ops-planner:\nInspect HVAC filters monthly.",
        "evidence_block": "### Grounded Document Evidence:\n- [doc-1]: Filter size MERV-13.",
    },
    "deliberation_revise": {
        "agent_title": "Operations Planner",
        "agent_id": "ops-planner",
        "topic": "Quarterly household maintenance schedule",
        "original_proposal": "Inspect HVAC filters monthly.",
        "feedback_block": "- From risk-reviewer: Specify MERV-13 replacement interval.",
    },
    "orch_eval_judge": {
        "prompt": "Help me organize my tax receipts and calendar deadlines.",
        "rubric": "Must address both document organization and deadline reminders.",
        "expected_agents": ["doc-organizer", "schedule-helper"],
        "answer": "Here is a folder structure for your receipts and a reminder checklist.",
    },
    "orch_eval_judge_system": {},
}


@pytest.mark.parametrize("template_name,context", list(EXTRACTED_TEMPLATES.items()))
def test_extracted_handlebars_templates_render_and_remain_domain_neutral(
    template_name: str,
    context: Dict[str, Any],
) -> None:
    loader = ResourceLoader()
    rendered = loader.render_template(template_name, context)
    assert rendered.strip(), f"Template {template_name} rendered empty output"
    assert not neutral_scan.PATTERN.search(rendered), (
        f"Template {template_name} leaked domain terms: {rendered}"
    )


def test_pack_override_for_handlebars_prompts(tmp_path: Path) -> None:
    pack_root = tmp_path / "packs" / "finance-pack"
    tpl_dir = pack_root / "resources" / "prompts" / "templates"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "skills_middleware.hbs").write_text(
        "## Finance Pack Skills\n{{{safety_boundary_notice}}}\nFollow pack ledger rules.",
        encoding="utf-8",
    )
    (tpl_dir / "db_query_planner.hbs").write_text(
        "PACK SQL PLANNER for {{{product_name}}}: {{{pack_instructions}}}",
        encoding="utf-8",
    )
    (tpl_dir / "tier1_domain_classifier.hbs").write_text(
        "PACK CLASSIFIER for {{{product_name}}}",
        encoding="utf-8",
    )

    resolver = PackResourceResolver("finance-pack", pack_root)
    loader = get_resource_loader()
    loader.register_pack(SimpleNamespace(id="finance-pack", routing_hints=None), resolver=resolver)
    try:
        overridden = compose_skills_system_prompt(
            safety_boundary_notice="Never fabricate tax return filings.",
            pack_id="finance-pack",
        )
        assert "## Finance Pack Skills" in overridden
        assert "Never fabricate tax return filings." in overridden
        assert "Follow pack ledger rules." in overridden

        # Core default remains unaffected when pack_id is omitted
        default_prompt = compose_skills_system_prompt(
            safety_boundary_notice="Never fabricate tax return filings."
        )
        assert "## Yarvelle Core Skill Catalog" in default_prompt
        assert "## Finance Pack Skills" not in default_prompt

        # Query planner and classifier helpers also honour pack overrides
        assert (
            compose_query_planner_prompt(
                product_name="Finance Suite",
                pack_instructions="Use ISO-4217 currency codes",
                pack_id="finance-pack",
            )
            == "PACK SQL PLANNER for Finance Suite: Use ISO-4217 currency codes"
        )
        assert (
            compose_tier1_classifier_prompt(
                product_name="Finance Suite",
                pack_id="finance-pack",
            )
            == "PACK CLASSIFIER for Finance Suite"
        )
    finally:
        loader.unregister_pack("finance-pack")


def test_generic_building_block_placeholder_resolution(tmp_path: Path) -> None:
    res_dir = tmp_path / "resources"
    res_dir.mkdir(parents=True)
    raw = {
        "building_blocks": {
            "base_units": ["usd", "eur", "gbp"],
            "amount_expr": r"\d+\s*(?:<BASE_UNITS>)",
        },
        "refusal_patterns": [
            {
                "category": "wire_limit",
                "description": "Block unverified wire transfer thresholds",
                "pattern": r"transfer\s+<AMOUNT_EXPR>",
            },
        ],
    }
    (res_dir / "refusal_patterns.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    loader = ResourceLoader(resources_dir=res_dir)
    blocks = loader._resolve_building_blocks()
    assert blocks["BASE_UNITS"] == "usd|eur|gbp"
    assert blocks["AMOUNT_EXPR"] == r"\d+\s*(?:usd|eur|gbp)"
    compiled = loader.get_compiled_refusal_patterns()
    assert len(compiled) == 1
    assert compiled[0].regex.search("Please transfer 500 EUR today") is not None


def test_core_target_files_have_zero_medical_or_phi_terms() -> None:
    core_root = Path(yarvelle_core.__file__).resolve().parent
    targets = [
        core_root / "resources" / "loader.py",
        core_root / "middleware" / "skills.py",
        core_root / "resources" / "errors.yaml",
        core_root / "engine" / "tool_registry.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        tokenized = neutral_scan.split_tokens(text)
        matches = {
            m.group(0).lower()
            for m in (*neutral_scan.PATTERN.finditer(tokenized), *neutral_scan.PATTERN.finditer(text))
        }
        assert not matches, f"{path.name} still contains disallowed domain terms: {sorted(matches)}"


def test_neutral_words_allowlist_has_zero_runtime_files_and_covers_new_terms() -> None:
    runtime_allowlisted = [
        path for path in neutral_scan.ALLOWLIST if not path.startswith("db/migrations/versions/")
    ]
    assert runtime_allowlisted == [], (
        f"Runtime source files must not appear in ALLOWLIST: {runtime_allowlisted}"
    )

    for sample in ("phi", "mrn", "healthcare", "dosing_units", "all_cessation_drugs"):
        assert neutral_scan.PATTERN.search(sample), f"PATTERN failed to match banned term {sample!r}"


def test_zero_unprefixed_connectors_imports_in_yarvelle_core() -> None:
    core_root = Path(yarvelle_core.__file__).resolve().parent
    offenders: List[str] = []

    for py_file in sorted(core_root.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        rel = py_file.relative_to(core_root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "connectors" or alias.name.startswith("connectors."):
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "connectors" or node.module.startswith("connectors."):
                    offenders.append(f"{rel}:{node.lineno} from {node.module} import ...")

    assert offenders == []
    assert "connectors" not in sys.modules


@pytest.mark.asyncio
async def test_builtin_tool_handlers_calendar_and_fail_closed_gmail_mcp() -> None:
    registry = create_default_registry()
    specs = registry.list_all()
    assert len(specs) > 0
    for spec in specs:
        assert callable(spec.executor), f"Built-in tool {spec.name!r} has non-callable executor"

    # 1. Calendar built-ins import GoogleCalendarConnector cleanly (no ModuleNotFoundError)
    cal_ctx = ToolContext(
        user_id="user-cal-1",
        profile_id="prof-cal-1",
        principal="user",
        run_id="run-cal-1",
        autonomy="A2",
        taint=TaintFlag(),
    )
    slots = await registry.get("calendar_suggest_slots").executor(
        {
            "window_start": "2026-11-12T09:00:00+00:00",
            "window_end": "2026-11-12T12:00:00+00:00",
            "duration_minutes": 30,
        },
        cal_ctx,
    )
    assert slots["connector_id"] == "google-calendar"
    assert len(slots["slots"]) >= 1

    created = await registry.get("calendar_create_event").executor(
        {
            "title": "Confidential Strategy Review",
            "start_time": "2026-11-12T10:00:00+00:00",
            "end_time": "2026-11-12T10:30:00+00:00",
            "strip_sensitive": True,
        },
        cal_ctx,
    )
    assert created["status"] == "created"
    assert created["title"] == "Scheduled Event"

    # 2. Gmail built-ins fail closed when no MCP client is configured (never fake success)
    bare_ctx = ToolContext(
        user_id="user-1",
        profile_id="prof-1",
        principal="user",
        run_id="run-52",
        autonomy="A3",
        taint=TaintFlag(),
    )
    with pytest.raises(ConnectorNotConfiguredError):
        await registry.get("gmail_list_messages").executor({"label": "STARRED"}, bare_ctx)

    with pytest.raises(ConnectorNotConfiguredError):
        await registry.get("gmail_send_message").executor(
            {"to": "person@example.com", "subject": "Hello", "body": "Body"},
            bare_ctx,
        )

    exec_res = await execute_tool_call(
        bare_ctx,
        registry.get("gmail_list_messages"),
        {"label": "STARRED"},
    )
    assert exec_res.success is False
    assert "not configured" in (exec_res.error or "")

    # 3. When a real MCP client is attached, Gmail handlers delegate and wrap untrusted output
    calls: List[tuple[str, Dict[str, Any]]] = []

    class _StubMcpClient:
        async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            calls.append((name, dict(arguments)))
            if name == "gmail_list_messages":
                return {"messages": [{"id": "m-1", "snippet": "Invoice attached"}], "total": 1}
            return {"message_id": "m-sent-1", "status": "sent"}

    mcp_ctx = ToolContext(
        user_id="user-1",
        profile_id="prof-1",
        principal="user",
        run_id="run-52b",
        autonomy="A3",
        taint=TaintFlag(),
        extra={"mcp_client": _StubMcpClient()},
    )
    listed = await registry.get("gmail_list_messages").executor(
        {"label": "STARRED", "max_results": 5},
        mcp_ctx,
    )
    assert isinstance(listed, UntrustedResult)
    assert listed.taint is True
    assert listed.data["total"] == 1

    sent = await registry.get("gmail_send_message").executor(
        {"to": "person@example.com", "subject": "Invoice", "body": "Attached"},
        mcp_ctx,
    )
    assert isinstance(sent, UntrustedResult)
    assert sent.taint is True
    assert sent.data["message_id"] == "m-sent-1"
    assert [c[0] for c in calls] == ["gmail_list_messages", "gmail_send_message"]


def test_migration_0014_renames_legacy_profile_columns(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mig0014.db'}")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        cfg = get_alembic_config(conn)
        command.upgrade(cfg, "0013_turn_tasks")

        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, email, hashed_password, full_name, role, status, auth_provider, created_at, updated_at) "
                "VALUES ('u1', 'alice', 'alice@example.com', 'x', 'Alice', 'steward', 'active', 'local', :now, :now)"
            ),
            {"now": now},
        )
        conn.execute(
            sa.text(
                "INSERT INTO profiles (id, user_id, name, relationship, role, avatar_color, is_primary, created_at, updated_at) "
                "VALUES ('p1', 'u1', 'Alice', 'self', 'self', '1', 1, :now, :now)"
            ),
            {"now": now},
        )
        conn.execute(
            sa.text(
                "INSERT INTO profile_consents (id, profile_id, terms_version, allow_clinical, teen_handover_notified, created_at, updated_at) "
                "VALUES ('c1', 'p1', 'v1.0', 1, 0, :now, :now)"
            ),
            {"now": now},
        )
        conn.execute(
            sa.text(
                "INSERT INTO profile_access (id, profile_id, user_id, role, access_level, granted_at) "
                "VALUES ('a1', 'p1', 'u1', 'viewer', 'view_clinical', :now)"
            ),
            {"now": now},
        )
        conn.execute(
            sa.text(
                "INSERT INTO viewer_invites (id, invite_code, profile_id, invited_by, invitee_name, role, view_clinical, view_paperwork, expires_at, created_at, updated_at) "
                "VALUES ('i1', 'inv-1', 'p1', 'u1', 'Bob', 'viewer', 1, 0, :now, :now, :now)"
            ),
            {"now": now},
        )

        command.upgrade(cfg, "0014_neutralize_profile_columns")

        consent_cols = {c["name"] for c in sa.inspect(conn).get_columns("profile_consents")}
        invite_cols = {c["name"] for c in sa.inspect(conn).get_columns("viewer_invites")}
        assert "allow_assist" in consent_cols and "allow_clinical" not in consent_cols
        assert "view_records" in invite_cols and "view_clinical" not in invite_cols

        allow_val = conn.execute(sa.text("SELECT allow_assist FROM profile_consents WHERE id = 'c1'")).scalar_one()
        view_val = conn.execute(sa.text("SELECT view_records FROM viewer_invites WHERE id = 'i1'")).scalar_one()
        level_val = conn.execute(sa.text("SELECT access_level FROM profile_access WHERE id = 'a1'")).scalar_one()
        assert bool(allow_val) is True
        assert bool(view_val) is True
        assert level_val == "view_records"

        # Verify downgrade and idempotent re-upgrade
        command.downgrade(cfg, "0013_turn_tasks")
        consent_cols_down = {c["name"] for c in sa.inspect(conn).get_columns("profile_consents")}
        assert "allow_clinical" in consent_cols_down and "allow_assist" not in consent_cols_down
        assert conn.execute(sa.text("SELECT access_level FROM profile_access WHERE id = 'a1'")).scalar_one() == "view_clinical"

        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        consent_cols_up = {c["name"] for c in sa.inspect(conn).get_columns("profile_consents")}
        assert "allow_assist" in consent_cols_up and "allow_clinical" not in consent_cols_up
