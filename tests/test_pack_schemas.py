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

"""Unit tests for canonical JSON schema generation and validation."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import pytest

from yarvelle_core.pack.spec import PackManifest
from yarvelle_core.schemas.generator import emit_canonical_schemas, generate_json_schema
from yarvelle_core.schemas.manifest import AgentManifest, SkillFrontmatter


def test_generate_pack_schema():
    """Verify pack JSON schema properties and metadata."""
    schema = generate_json_schema(
        PackManifest,
        title="Yarvelle Pack Manifest Schema (Pack API v1)",
        schema_id="https://schemas.yarvelle.org/v1/pack.schema.json",
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://schemas.yarvelle.org/v1/pack.schema.json"
    assert schema["title"] == "Yarvelle Pack Manifest Schema (Pack API v1)"
    assert "properties" in schema
    assert "id" in schema["properties"]
    assert "domain" in schema["properties"]
    assert "requires_core" in schema["properties"]
    assert "scopes" in schema["properties"]


def test_generate_agent_and_skill_schemas():
    """Verify agent and skill schemas metadata and required fields."""
    agent_schema = generate_json_schema(
        AgentManifest,
        title="Yarvelle Agent Manifest Schema",
        schema_id="https://schemas.yarvelle.org/v1/agent.schema.json",
    )
    assert agent_schema["$id"] == "https://schemas.yarvelle.org/v1/agent.schema.json"
    assert "id" in agent_schema["properties"]

    skill_schema = generate_json_schema(
        SkillFrontmatter,
        title="Yarvelle Skill Frontmatter Schema",
        schema_id="https://schemas.yarvelle.org/v1/skill.schema.json",
    )
    assert skill_schema["$id"] == "https://schemas.yarvelle.org/v1/skill.schema.json"
    assert "name" in skill_schema["properties"]


def test_emit_canonical_schemas(tmp_path: Path):
    """Verify emission of schemas to disk with valid JSON."""
    out_dir = tmp_path / "schemas"
    schemas = emit_canonical_schemas([out_dir])

    assert "pack.schema.json" in schemas
    assert "agent.schema.json" in schemas
    assert "skill.schema.json" in schemas

    for filename in ("pack.schema.json", "agent.schema.json", "skill.schema.json"):
        target_file = out_dir / filename
        assert target_file.exists()
        loaded = json.loads(target_file.read_text(encoding="utf-8"))
        assert loaded["$id"] == schemas[filename]["$id"]


def test_canonical_schemas_committed_freshness():
    """Verify that committed schema files in schemas/ and src/yarvelle_core/schemas/ match live models.

    Fails with an exact unified diff if any committed schema file has drifted from the
    authoritative Pydantic models, ensuring developers must run scripts/generate_schemas.py
    whenever models or enums change.
    """
    repo_root = Path(__file__).resolve().parent.parent
    target_dirs = [
        repo_root / "schemas",
        repo_root / "src" / "yarvelle_core" / "schemas",
    ]

    schema_specs = [
        (
            "pack.schema.json",
            PackManifest,
            "Yarvelle Pack Manifest Schema (Pack API v1)",
            "https://schemas.yarvelle.org/v1/pack.schema.json",
        ),
        (
            "agent.schema.json",
            AgentManifest,
            "Yarvelle Agent Manifest Schema",
            "https://schemas.yarvelle.org/v1/agent.schema.json",
        ),
        (
            "skill.schema.json",
            SkillFrontmatter,
            "Yarvelle Skill Frontmatter Schema",
            "https://schemas.yarvelle.org/v1/skill.schema.json",
        ),
    ]

    drift_failures: list[str] = []

    for target_dir in target_dirs:
        for filename, model_cls, title, schema_id in schema_specs:
            schema_file = target_dir / filename
            assert schema_file.exists(), f"Committed schema file does not exist: {schema_file}"

            committed_content = schema_file.read_text(encoding="utf-8")
            live_schema = generate_json_schema(model_cls, title=title, schema_id=schema_id)
            expected_content = json.dumps(live_schema, indent=2) + "\n"

            if committed_content != expected_content:
                rel_path = schema_file.relative_to(repo_root)
                diff = difflib.unified_diff(
                    committed_content.splitlines(keepends=True),
                    expected_content.splitlines(keepends=True),
                    fromfile=f"committed/{rel_path}",
                    tofile=f"generated/{filename}",
                )
                drift_failures.append(
                    f"Drift in {rel_path} (Model: {model_cls.__name__}):\n{''.join(diff)}"
                )

    if drift_failures:
        msg = (
            f"Schema drift detected across {len(drift_failures)} committed schema file(s)!\n\n"
            + "\n".join(drift_failures)
            + "\n\nRemediation:\n"
            + "  Run '/Users/bharatjoshi/git/carefold/backend/.venv/bin/python scripts/generate_schemas.py' "
            + "and commit the regenerated schema files."
        )
        pytest.fail(msg)


def test_manifest_validation_valid():
    """Verify PackManifest model validation with valid payload."""
    raw = {
        "pack_api": 1,
        "id": "finance",
        "name": "Household Finance",
        "version": "1.0.0",
        "domain": "finance",
        "requires_core": ">=0.1.0",
        "scopes": [
            {"id": "finance.accounts", "description": "Accounts", "sensitivity": "internal"}
        ],
    }
    manifest = PackManifest.model_validate(raw)
    assert manifest.id == "finance"
    assert manifest.domain == "finance"
    assert len(manifest.scopes) == 1


def test_manifest_validation_invalid_slug():
    """Verify PackManifest model validation rejects invalid domain or id slugs."""
    raw = {
        "pack_api": 1,
        "id": "INVALID ID WITH SPACES",
        "name": "Household Finance",
        "version": "1.0.0",
        "domain": "finance",
        "requires_core": ">=0.1.0",
    }
    with pytest.raises(ValueError):
        PackManifest.model_validate(raw)
