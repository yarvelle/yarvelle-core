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

"""Canonical JSON Schema exporter for packs, agents, and skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel

from yarvelle_core.pack.spec import PackManifest
from yarvelle_core.schemas.manifest import AgentManifest, SkillFrontmatter


def generate_json_schema(model_cls: type[BaseModel], title: str, schema_id: str) -> Dict[str, Any]:
    """Generates standard JSON Schema draft 2020-12 for a Pydantic v2 model."""
    schema = model_cls.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = schema_id
    schema["title"] = title
    return schema


def emit_canonical_schemas(
    target_dirs: List[Path],
) -> Dict[str, Dict[str, Any]]:
    """Emits pack.schema.json, agent.schema.json, and skill.schema.json to target directories."""
    schemas = {
        "pack.schema.json": generate_json_schema(
            PackManifest,
            title="Yarvelle Pack Manifest Schema (Pack API v1)",
            schema_id="https://schemas.yarvelle.org/v1/pack.schema.json",
        ),
        "agent.schema.json": generate_json_schema(
            AgentManifest,
            title="Yarvelle Agent Manifest Schema",
            schema_id="https://schemas.yarvelle.org/v1/agent.schema.json",
        ),
        "skill.schema.json": generate_json_schema(
            SkillFrontmatter,
            title="Yarvelle Skill Frontmatter Schema",
            schema_id="https://schemas.yarvelle.org/v1/skill.schema.json",
        ),
    }

    for dir_path in target_dirs:
        dir_path.mkdir(parents=True, exist_ok=True)
        for filename, schema_dict in schemas.items():
            out_file = dir_path / filename
            out_file.write_text(json.dumps(schema_dict, indent=2) + "\n", encoding="utf-8")

    return schemas


__all__ = [
    "emit_canonical_schemas",
    "generate_json_schema",
]
