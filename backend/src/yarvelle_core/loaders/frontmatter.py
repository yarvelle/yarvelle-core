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

"""Markdown frontmatter parser and mandatory intended-use verifier."""

from __future__ import annotations

import re
from typing import Any, Dict, NamedTuple, Optional, Tuple
import yaml


from yarvelle_core.resources.loader import get_resource_loader


class ParsedFrontmatter(NamedTuple):
    frontmatter: Dict[str, Any]
    body: str


MANDATORY_INTENDED_USE_LINES = get_resource_loader().get_mandatory_intended_use_lines()


def parse_frontmatter(markdown: str) -> ParsedFrontmatter:
    """Extracts and parses YAML frontmatter from a markdown string."""
    normalized = markdown.replace("\r\n", "\n")
    match = re.match(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$", normalized)

    if not match:
        return ParsedFrontmatter(frontmatter={}, body=normalized.strip())

    raw_yaml = match.group(1)
    body = match.group(2).strip()

    try:
        parsed = yaml.safe_load(raw_yaml) or {}
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception as err:
        raise ValueError(f"Malformed YAML frontmatter in SKILL.md: {err}") from err

    return ParsedFrontmatter(frontmatter=parsed, body=body)


def check_mandatory_intended_use(content: str) -> Tuple[bool, Optional[str]]:
    """Checks whether the content includes all pack-configured mandatory intended-use statements.

    Returns (True, None) if all required lines are present, or (False, missing_line) if any is missing.
    """
    normalized = content.lower()

    for line in MANDATORY_INTENDED_USE_LINES:
        if line.lower() not in normalized:
            return False, line

    return True, None
