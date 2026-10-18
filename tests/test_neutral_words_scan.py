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
    r"\bclinic(al)?\b",
    r"\bplaid\b",
    r"\bhomework\b",
    r"\bgradebook\b",
]

PATTERN = re.compile("|".join(DISALLOWED_TERMS), re.IGNORECASE)

# Explicitly audited allowlist for protocol backward compatibility
ALLOWLIST = {
    # HKDF backward compatibility test check for legacy 'health' DEK path
    "vault/dek.py": {"health"},
}


def test_yarvelle_core_neutral_words():
    """Scan all Python files in yarvelle_core to ensure zero domain contamination."""
    core_root = Path(yarvelle_core.__file__).resolve().parent
    violations: List[Tuple[str, int, str]] = []

    for py_file in core_root.rglob("*.py"):
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

            matches = PATTERN.findall(line)
            if matches:
                # Check allowlist
                allowed = False
                for allow_path, terms in ALLOWLIST.items():
                    if rel_path.endswith(allow_path):
                        if all(m.lower() in terms for m in matches):
                            allowed = True
                            break
                if not allowed:
                    violations.append((rel_path, idx, line.strip()))

    assert len(violations) == 0, (
        f"Found {len(violations)} domain word violations in core modules:\n"
        + "\n".join(f"{path}:{line}: {content}" for path, line, content in violations[:10])
    )
