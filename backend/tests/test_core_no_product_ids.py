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
to domain packs and applications. This test fails when:

1. A known product specialist agent id appears anywhere in core source, the
   bundled agents and skill template, or the canonical schemas. There is no
   allowlist for these.
2. The downstream product name appears in a file that is not pinned below, or
   more often than its pin. The pins cover runtime identity that a separate,
   coordinated rename has to move (environment variable names, the home
   directory and database file name, cookies, OAuth client ids, the relay URL
   scheme, service unit names, locale strings) and values that are pinned for
   compatibility forever (vault salt and keyring service names). The pins can
   only go down: when a count drops, lower or delete its pin in the same change.

The id list is a deny-list, so it necessarily names the ids it forbids.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Dict, Iterator, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = (
    "backend/src/yarvelle_core",
    "agents",
    "skills/_template",
    "schemas",
)

TEXT_SUFFIXES = {
    ".py", ".yaml", ".yml", ".md", ".json", ".mako", ".hbs", ".txt",
    ".toml", ".jinja", ".j2", ".html", ".ini", ".cfg",
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

# path (relative to the repository root) -> maximum allowed occurrences.
PRODUCT_NAME_PINS: Dict[str, int] = {
    "backend/src/yarvelle_core/api/attachments.py": 5,
    "backend/src/yarvelle_core/api/connections.py": 1,
    "backend/src/yarvelle_core/api/deps.py": 1,
    "backend/src/yarvelle_core/audit/logger.py": 1,
    "backend/src/yarvelle_core/auth/adapters/disabled_adapter.py": 1,
    "backend/src/yarvelle_core/auth/adapters/oidc_adapter.py": 2,
    "backend/src/yarvelle_core/auth/factory.py": 2,
    "backend/src/yarvelle_core/config.py": 22,
    "backend/src/yarvelle_core/connectors/lifecycle.py": 1,
    "backend/src/yarvelle_core/connectors/loader.py": 4,
    "backend/src/yarvelle_core/connectors/oauth.py": 3,
    "backend/src/yarvelle_core/connectors/relay.py": 6,
    "backend/src/yarvelle_core/connectors/starters/__init__.py": 2,
    "backend/src/yarvelle_core/constants/__init__.py": 2,
    "backend/src/yarvelle_core/constants/models.py": 1,
    "backend/src/yarvelle_core/constants/paths.py": 10,
    "backend/src/yarvelle_core/db/models.py": 1,
    "backend/src/yarvelle_core/db/session.py": 1,
    "backend/src/yarvelle_core/engine/agent_factory.py": 1,
    "backend/src/yarvelle_core/engine/graph.py": 2,
    "backend/src/yarvelle_core/memory/factory.py": 3,
    "backend/src/yarvelle_core/migration/runtime_migrator.py": 14,
    "backend/src/yarvelle_core/model/egress.py": 8,
    "backend/src/yarvelle_core/model/providers/ollama_provider.py": 1,
    "backend/src/yarvelle_core/packaging/service.py": 25,
    "backend/src/yarvelle_core/platform/reminders.py": 1,
    "backend/src/yarvelle_core/resources/locales/ar-SA.json": 12,
    "backend/src/yarvelle_core/resources/locales/en-US.json": 12,
    "backend/src/yarvelle_core/resources/locales/es-ES.json": 12,
    "backend/src/yarvelle_core/resources/locales/fr-FR.json": 12,
    "backend/src/yarvelle_core/resources/locales/hi-IN.json": 12,
    "backend/src/yarvelle_core/search/factory.py": 3,
    "backend/src/yarvelle_core/storage/adapters/local_adapter.py": 1,
    "backend/src/yarvelle_core/storage/cas.py": 13,
    "backend/src/yarvelle_core/storage/factory.py": 1,
    "backend/src/yarvelle_core/tools/attach_read.py": 1,
    "backend/src/yarvelle_core/tools/web_search.py": 5,
    "backend/src/yarvelle_core/tools/workspace_note.py": 1,
    "backend/src/yarvelle_core/vault/kek.py": 10,
}


def _iter_files() -> Iterator[Tuple[str, str]]:
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
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


def test_product_name_only_in_pinned_files() -> None:
    _require_source()
    problems: List[str] = []
    seen: Dict[str, int] = {}
    for rel, text in _iter_files():
        count = len(PRODUCT_NAME.findall(text))
        if count:
            seen[rel] = count
        pin = PRODUCT_NAME_PINS.get(rel, 0)
        if count > pin:
            problems.append(f"{rel}: {count} occurrence(s), pinned at {pin}")
        elif count < pin:
            problems.append(f"{rel}: {count} occurrence(s), pin is {pin}; lower the pin to {count}")
    for rel in PRODUCT_NAME_PINS:
        if rel not in seen and (REPO_ROOT / rel).exists():
            continue
        if rel not in seen:
            problems.append(f"{rel}: file is gone; delete its pin")
    assert not problems, "Product name pins are out of date:\n" + "\n".join(problems)


def test_id_patterns_catch_both_spellings() -> None:
    sample_hyphen = "route to visit-steward"
    sample_snake = "AGENT_VISIT_STEWARD = visit_steward"
    assert any(p.search(sample_hyphen) for p in _ID_PATTERNS)
    assert any(p.search(sample_snake) for p in _ID_PATTERNS)
    assert not any(p.search("document-extractor and budget-planner") for p in _ID_PATTERNS)
