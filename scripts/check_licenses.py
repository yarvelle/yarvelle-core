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

"""Validate that all Python files in yarvelle-core carry the official license header."""
from pathlib import Path
import sys

REQUIRED_HEADER = """# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)"""

APACHE_MARKER = "Licensed under the Apache License, Version 2.0"


def check_file(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    if APACHE_MARKER in content:
        return True  # Preserved historical Apache header
    # Allow optional shebang line before REQUIRED_HEADER
    if content.startswith("#!"):
        first_newline = content.find("\n")
        if first_newline != -1:
            rest = content[first_newline + 1:]
            return rest.startswith(REQUIRED_HEADER)
    return content.startswith(REQUIRED_HEADER)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    violations = []
    for p in root.rglob("*.py"):
        if any(skip in p.parts for skip in [".venv", "venv", "__pycache__", ".git", "build", "dist", ".tox", ".nox"]):
            continue
        if not check_file(p):
            violations.append(str(p.relative_to(root)))

    if violations:
        print(f"License header missing or invalid in {len(violations)} files:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("All Python files have valid license headers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
