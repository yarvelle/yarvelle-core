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

"""Packaging test asserting that built wheels contain force-included content and entry points."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile
import pytest


def test_wheel_contains_all_content_and_entry_points(tmp_path: Path):
    """Builds distribution wheel and inspects that all required agents, skills, and schemas are bundled."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    backend_dir = repo_root / "backend"
    out_dir = tmp_path / "wheel_dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build wheel using python -m build --wheel
    cmd = [
        sys.executable,
        "-m",
        "build",
        "--wheel",
        str(backend_dir),
        "--outdir",
        str(out_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Failed to build wheel:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    wheel_files = list(out_dir.glob("*.whl"))
    assert len(wheel_files) == 1, f"Expected 1 wheel file in {out_dir}, found: {wheel_files}"
    wheel_path = wheel_files[0]

    with zipfile.ZipFile(wheel_path, "r") as z:
        names = set(z.namelist())

        required_content_files = [
            "yarvelle_core/_content/agents/_system/orchestrator/agent.yaml",
            "yarvelle_core/_content/agents/_system/document-extractor/agent.yaml",
            "yarvelle_core/_content/agents/_system/skill-generator/agent.yaml",
            "yarvelle_core/_content/agents/_system/suggestion-generator/agent.yaml",
            "yarvelle_core/_content/agents/_template/agent.yaml",
            "yarvelle_core/_content/skills/_template/SKILL.md",
            "yarvelle_core/_content/schemas/pack.schema.json",
            "yarvelle_core/_content/schemas/agent.schema.json",
            "yarvelle_core/_content/schemas/skill.schema.json",
        ]

        missing = [f for f in required_content_files if f not in names]
        assert not missing, f"Built wheel is missing required force-included files: {missing}"

        # Inspect entry_points.txt in .dist-info
        entry_points_files = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        assert len(entry_points_files) == 1, f"Expected 1 entry_points.txt file, found: {entry_points_files}"
        ep_content = z.read(entry_points_files[0]).decode("utf-8")

        assert "[console_scripts]" in ep_content
        assert "yarvelle-core = yarvelle_core.cli:main" in ep_content
