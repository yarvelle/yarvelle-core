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

"""Guard: core must not carry product agent ids or the downstream product name.

Core is domain-neutral. Specialist agents, their ids, and product branding belong
to domain packs and applications. Runtime identity (environment variable prefix,
home directory, database file, cookie, OAuth client ids, URL scheme, keychain
service, vault salt) comes from ``yarvelle_core.identity`` settings, so core needs
no product names at all. This test fails when:

1. A known product specialist agent id appears in core source, the bundled
   agents and skill template, the canonical schemas, or the frontend.
2. The downstream product name appears, in any letter case, in a file path or a
   file's text anywhere in that scope, including migrations, prompts, locales
   and templates. There are no allowances.

The lists below are deny-lists, so they necessarily name what they forbid.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterator, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = (
    "backend/src/yarvelle_core",
    "agents",
    "skills/_template",
    "schemas",
    "frontend/src",
    "frontend/bin",
    "frontend/scripts",
    "frontend/stories",
    "frontend/tokens",
)

SCAN_FILES = (
    "frontend/package.json",
    "backend/pyproject.toml",
)

SKIP_PARTS = {"__pycache__", ".venv", "node_modules", "dist"}

TEXT_SUFFIXES = {
    ".py", ".yaml", ".yml", ".md", ".json", ".mako", ".hbs", ".txt",
    ".toml", ".jinja", ".j2", ".html", ".ini", ".cfg",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".svg",
    ".sql",
}

# Specialist agent ids that belong to a downstream product pack, never to core.
PRODUCT_AGENT_IDS = (
    "visit-steward",
    "benefits-guide",
    "habit-companion",
    "appointment-prep-coordinator",
    "cardiology-guide",
    "nephrology-guide",
    "pulmonology-guide",
    "neurology-guide",
    "gastro-guide",
    "endocrinology-guide",
    "ortho-guide",
    "derma-guide",
    "rheuma-guide",
    "urology-guide",
    "eye-guide",
    "ent-guide",
    "oncology-navigator",
    "formulary-guide",
    "claims-appeals-guide",
    "prior-auth-navigator",
    "records-coordinator",
    "carefold-agent",
    "carefold-default",
)

# Python-identifier spellings of the same ids (constants, prompt catalog keys).
_ID_PATTERNS = [
    re.compile(r"(?<![a-z0-9-])" + re.escape(agent_id).replace("\\-", "[-_]") + r"(?![a-z0-9-])", re.IGNORECASE)
    for agent_id in PRODUCT_AGENT_IDS
]

PRODUCT_NAME = re.compile(r"carefold", re.IGNORECASE)

def _iter_paths() -> Iterator[Path]:
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if SKIP_PARTS.intersection(path.relative_to(REPO_ROOT).parts):
                continue
            yield path
    for rel in SCAN_FILES:
        path = REPO_ROOT / rel
        if path.is_file():
            yield path


def _iter_files() -> Iterator[Tuple[str, str]]:
    for path in _iter_paths():
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def _require_source() -> None:
    if not (REPO_ROOT / "backend/src/yarvelle_core").is_dir():
        pytest.skip("core source tree not available")


def test_no_product_agent_ids_in_core() -> None:
    _require_source()
    hits: List[str] = []
    for rel, text in _iter_files():
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in _ID_PATTERNS:
                if pattern.search(line):
                    hits.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert not hits, "Product agent ids found in core (move them to the pack):\n" + "\n".join(hits)


def test_product_name_absent_from_core() -> None:
    _require_source()
    hits: List[str] = []
    for path in _iter_paths():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if PRODUCT_NAME.search(rel):
            hits.append(f"{rel}: product name in path")
    for rel, text in _iter_files():
        for lineno, line in enumerate(text.splitlines(), 1):
            if PRODUCT_NAME.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert not hits, (
        "Product name found in core (use yarvelle_core.identity settings or move it to the app):\n"
        + "\n".join(hits)
    )


def test_product_name_pattern_is_case_insensitive() -> None:
    for sample in ("carefold", "Carefold", "CAREFOLD_HOME", "~/.carefold", "carefold://x"):
        assert PRODUCT_NAME.search(sample)


def test_id_patterns_catch_both_spellings() -> None:
    sample_hyphen = "route to visit-steward"
    sample_snake = "AGENT_VISIT_STEWARD = visit_steward"
    assert any(p.search(sample_hyphen) for p in _ID_PATTERNS)
    assert any(p.search(sample_snake) for p in _ID_PATTERNS)
    assert not any(p.search("document-extractor and budget-planner") for p in _ID_PATTERNS)
