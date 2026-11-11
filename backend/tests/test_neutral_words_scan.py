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

Verifies that domain-specific health/clinical/PHI, finance, and education terms
do not leak into domain-neutral core runtime files.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import List, Tuple

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
    r"\bphi\b",
    r"\bmrn\b",
    r"\bhealthcare\b",
    r"\bdosing_units\b",
    r"\ball_cessation_drugs\b",
]

PATTERN = re.compile("|".join(DISALLOWED_TERMS), re.IGNORECASE)

# Historical Alembic migration revisions only; zero runtime source files are allowlisted.
ALLOWLIST = {
    "db/migrations/versions/0001_baseline_schema.py": {"clinical"},
    "db/migrations/versions/0005_clinical_domain_records.py": {"clinical", "clinic"},
    "db/migrations/versions/0006_preventive_and_school_forms.py": {"clinical"},
    "db/migrations/versions/0009_companion_and_handover.py": {"clinical"},
    "db/migrations/versions/0011_scopes.py": {"clinical"},
    "db/migrations/versions/0014_neutralize_profile_columns.py": {"clinical"},
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
        rel_path = py_file.relative_to(core_root).as_posix()
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
            matches = sorted(
                {
                    m.group(0).lower()
                    for m in (*PATTERN.finditer(tokenized), *PATTERN.finditer(line))
                }
            )
            if matches:
                allowed = False
                for allow_path, terms in ALLOWLIST.items():
                    if rel_path == allow_path:
                        if all(m in terms for m in matches):
                            allowed = True
                            break
                if not allowed:
                    violations.append((rel_path, idx, line.strip(), matches))

    assert len(violations) == 0, (
        f"Found {len(violations)} domain word violations in core modules:\n"
        + "\n".join(f"{path}:{line}: {matches} in: {content}" for path, line, content, matches in violations[:15])
    )
