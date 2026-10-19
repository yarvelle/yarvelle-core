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

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Hatchling build hook force-including top-level agents, skills, and schemas."""

    def initialize(self, version: str, build_data: Dict[str, Any]) -> None:
        root = Path(self.root).parent  # top-level repo root
        force_include = build_data.setdefault("force_include", {})

        agents_dir = root / "agents"
        skills_dir = root / "skills"
        schemas_dir = root / "schemas"

        if agents_dir.is_dir():
            force_include[str(agents_dir)] = "yarvelle_core/_content/agents"
        if skills_dir.is_dir():
            force_include[str(skills_dir)] = "yarvelle_core/_content/skills"
        if schemas_dir.is_dir():
            force_include[str(schemas_dir)] = "yarvelle_core/_content/schemas"
