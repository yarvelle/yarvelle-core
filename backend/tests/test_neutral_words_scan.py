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

"""Neutral Words Scan Test for Yarvelle Core Modules.

Verifies that domain-specific health, finance, and education terms do not leak
into domain-neutral core runtime files.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import List, Tuple
import pytest

import yarvelle_core

# Strict domain-specific terms that must NOT appear in core runtime logic
DISALLOWED_TERMS = [
    r"\bdoctor\b",
    r"\bpatient\b",
    r"\bvitals?\b",
    r"\bfhir\b",
    r"\bhipaa\b",
    r"\bdiagnosis\b",
    r"\bprescription\b",
    r"\bhospital\b",
    r"\bclinic(?:al)?\b",
    r"\bplaid\b",
    r"\bhomework\b",
    r"\bgradebook\b",
]

PATTERN = re.compile("|".join(DISALLOWED_TERMS), re.IGNORECASE)

# Explicitly audited allowlist for protocol and database backward compatibility
ALLOWLIST = {
    # HKDF backward compatibility test check for legacy 'health' DEK path
    "vault/dek.py": {"health"},
    # Historical Alembic migrations preserving pre-split schema baseline
    "db/migrations/versions/0001_baseline_schema.py": {"clinical"},
    "db/migrations/versions/0005_clinical_domain_records.py": {"clinical", "clinic"},
    "db/migrations/versions/0006_preventive_and_school_forms.py": {"clinical"},
    "db/migrations/versions/0009_companion_and_handover.py": {"clinical"},
    "db/migrations/versions/0011_scopes.py": {"clinical"},
    "db/session.py": {"clinical"},
    # Dual-write backward compatibility for legacy profile access fields (PROJECT.md R2)
    "db/models.py": {"clinical"},
    "schemas/profiles.py": {"clinical"},
    "scope/adapter.py": {"clinical"},
    "api/profiles.py": {"clinical"},
    "api/connections.py": {"clinical"},
    "api/reminders.py": {"clinical"},
    "api/email_drafts.py": {"clinical"},
    "api/attachments.py": {"clinical"},
    "api/routines.py": {"clinical"},
    "api/chat.py": {"clinical"},
    "api/skills.py": {"clinical"},
    "schemas/chat.py": {"clinical"},
    "schemas/manifest.py": {"clinical"},
    "constants/agents.py": {"clinical"},
    "engine/service.py": {"clinical"},
    "engine/runner.py": {"clinical"},
    "engine/safety_policy.py": {"clinical"},
    "engine/job_runner.py": {"clinical"},
    "engine/tool_registry.py": {"clinical"},
    "loaders/agent_loader.py": {"clinical"},
    "workflows/nodes/input_guardrail_node.py": {"clinical"},
    "workflows/nodes/agent_execution_node.py": {"clinical"},
    "workflows/state.py": {"clinical", "diagnosis"},
    # Transitional tool & search modules before Step C3 health pack split (M4)
    "search/chunker.py": {"clinical"},
    "search/adapters/spector.py": {"clinical"},
    "search/adapters/sqlite.py": {"clinical"},
    "search/__init__.py": {"clinical"},
    "tools/registry.py": {"clinical"},
    "tools/web_search.py": {"clinical"},
    "platform/email_drafts.py": {"clinical"},
    "connectors/base.py": {"patient", "clinical"},
    "connectors/manifest.py": {"clinical"},
    "connectors/starters/calendar.py": {"clinic", "clinical", "doctor"},
}


def split_tokens(text: str) -> str:
    """Split camelCase, PascalCase, and snake_case into space-delimited words.

    Ensures compound identifiers like 'ClinicalVisitDossier' or
    'PROMPT_EXTRACTION_CLINICAL_KEY' cannot bypass word-boundary regex detection.
    """
    # Split camelCase and PascalCase
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    # Split underscores and non-alphanumeric characters
    s = re.sub(r"[_\W]+", " ", s)
    return s


def test_yarvelle_core_neutral_words():
    """Scan all Python files in yarvelle_core to ensure zero domain contamination."""
    core_root = Path(yarvelle_core.__file__).resolve().parent
    violations: List[Tuple[str, int, str, List[str]]] = []

    for py_file in sorted(core_root.rglob("*.py")):
        rel_path = str(py_file.relative_to(core_root))
        # Skip conformance fixtures since they intentionally model domain test doubles
        if "conformance/fixtures" in rel_path:
            continue

        lines = py_file.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            tokenized = split_tokens(line)
            matches = [m.group(0) for m in PATTERN.finditer(tokenized)]
            if matches:
                # Check allowlist
                allowed = False
                for allow_path, terms in ALLOWLIST.items():
                    if rel_path.endswith(allow_path):
                        if all(m.lower() in terms for m in matches):
                            allowed = True
                            break
                if not allowed:
                    violations.append((rel_path, idx, line.strip(), matches))

    assert len(violations) == 0, (
        f"Found {len(violations)} domain word violations in core modules:\n"
        + "\n".join(f"{path}:{line}: {matches} in: {content}" for path, line, content, matches in violations[:15])
    )
