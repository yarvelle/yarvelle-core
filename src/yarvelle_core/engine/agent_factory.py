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

"""Deep Agents agent factory and native subagent loader facade."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from yarvelle_core.constants.paths import AGENTS_DIR, SKILLS_DIR
from yarvelle_core.loaders.agent_loader import load_subagent_from_yaml
from yarvelle_core.middleware.skills import create_yarvelle_skills_middleware
from yarvelle_core.tools.registry import CLOSED_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

try:
    from deepagents import (
        HarnessProfileConfig,
        create_deep_agent,
        register_harness_profile,
    )
except ImportError:
    HarnessProfileConfig = None  # type: ignore
    create_deep_agent = None  # type: ignore
    register_harness_profile = None  # type: ignore


def load_all_subagents(
    agents_dir: Union[Path, str],
    resolve_tools: bool = False,
) -> List[Dict[str, Any]]:
    """Discovers and parses all specialist agents into native SubAgent dicts."""
    base_dir = Path(agents_dir).resolve()
    subagents: List[Dict[str, Any]] = []
    if not base_dir.is_dir():
        return subagents

    for entry in sorted(base_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            try:
                sub = load_subagent_from_yaml(entry, resolve_tools=resolve_tools)
                subagents.append(sub)
            except Exception as err:
                logger.debug("Skipping invalid agent directory %s: %s", entry.name, err)
                continue
    return subagents


def create_yarvelle_agent(
    model: Any = "ollama:llama3.2",
    workspace_root: Optional[Union[Path, str]] = None,
    checkpointer: Optional[Any] = None,
    additional_middleware: Optional[List[Any]] = None,
) -> Any:
    """Convenience constructor assembling Deep Agents runtime with Yarvelle Core middleware."""
    if create_deep_agent is None:
        raise RuntimeError("deepagents package is required for native Deep Agents runtime.")

    ws = Path(workspace_root or ".").resolve()
    agents_dir = ws / AGENTS_DIR
    skills_dir = ws / SKILLS_DIR

    subagents = load_all_subagents(agents_dir, resolve_tools=True)

    # Resolve Phase 0 tool strings to tool schema dictionaries for subagent compilation
    resolved_subagents: List[Dict[str, Any]] = []
    for sub in subagents:
        sub_copy = dict(sub)
        mapped_tools: List[Any] = []
        for t in sub.get("tools", []):
            if isinstance(t, str) and t in CLOSED_TOOL_DEFINITIONS:
                mapped_tools.append(CLOSED_TOOL_DEFINITIONS[t])
            else:
                mapped_tools.append(t)
        sub_copy["tools"] = mapped_tools
        resolved_subagents.append(sub_copy)

    # Register harness profile if present
    profile_path = ws / "yarvelle-profile.yaml"
    if not profile_path.is_file():
        profile_path = ws / "carefold-profile.yaml"

    if profile_path.is_file() and HarnessProfileConfig is not None and register_harness_profile is not None:
        try:
            profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            # Unwrap nested harness dictionary
            harness_data = profile_data.get("harness", profile_data) if isinstance(profile_data, dict) else profile_data
            cfg = HarnessProfileConfig.from_dict(harness_data)

            model_keys = ["ollama:llama3.2", "google_genai:gemini-3.6-flash", "anthropic:claude-sonnet-4-6"]
            if isinstance(model, str) and model not in model_keys:
                model_keys.append(model)
            for m in model_keys:
                register_harness_profile(m, cfg)
        except Exception as err:
            logger.warning("Failed to register harness profile from %s: %s", profile_path, err)

    # Wire middlewares
    middleware = [
        create_yarvelle_skills_middleware(skills_dir),
    ]
    if additional_middleware:
        middleware.extend(additional_middleware)

    return create_deep_agent(
        model=model,
        subagents=resolved_subagents,
        middleware=middleware,
        checkpointer=checkpointer,
    )


__all__ = [
    "create_yarvelle_agent",
    "load_all_subagents",
    "load_subagent_from_yaml",
]
