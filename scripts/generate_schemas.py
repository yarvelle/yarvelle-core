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

"""CLI script to generate canonical JSON schemas for Pack, Agent, and Skill manifests."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure src is in pythonpath
repo_root = Path(__file__).resolve().parent.parent
src_dir = repo_root / "backend" / "src"
if not src_dir.exists():
    src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from yarvelle_core.schemas.generator import emit_canonical_schemas


def main() -> None:
    targets = [
        src_dir / "yarvelle_core" / "schemas",
        repo_root / "schemas",
    ]
    schemas = emit_canonical_schemas(targets)
    print(f"Successfully generated {len(schemas)} canonical JSON schemas:")
    for name in schemas:
        print(f"  - {name}")
    for target in targets:
        print(f"Written to: {target}")


if __name__ == "__main__":
    main()
