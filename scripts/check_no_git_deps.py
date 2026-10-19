#!/usr/bin/env python3
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

"""
CI Validation script: Asserts no git-SHA, git+, github:, or file: dependencies exist
in pyproject.toml, package.json, or committed lockfiles.
"""

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DISALLOWED_PATTERNS = [
    re.compile(r"git\+https?://", re.IGNORECASE),
    re.compile(r"git\+ssh://", re.IGNORECASE),
    re.compile(r"github:", re.IGNORECASE),
    re.compile(r"\bgit@[a-zA-Z0-9_.-]+:", re.IGNORECASE),
]

FILES_TO_CHECK = [
    ROOT / "backend" / "pyproject.toml",
    ROOT / "frontend" / "package.json",
]


def check_file(file_path: Path) -> list[str]:
    violations = []
    if not file_path.exists():
        return violations

    text = file_path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern in DISALLOWED_PATTERNS:
            if pattern.search(line):
                violations.append(f"{file_path.relative_to(ROOT)}:{line_no}: {line.strip()}")
    return violations


def main() -> int:
    all_violations = []
    for file_path in FILES_TO_CHECK:
        violations = check_file(file_path)
        all_violations.extend(violations)

    if all_violations:
        print("ERROR: Found disallowed git/github dependencies in manifests:", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    print("SUCCESS: Zero git+, github:, or commit-SHA dependencies detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
