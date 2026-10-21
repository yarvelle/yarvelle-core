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

        assert "yarvelle_core/cli.py" in names, "Built wheel is missing yarvelle_core/cli.py module"

        # Inspect entry_points.txt in .dist-info
        entry_points_files = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        assert len(entry_points_files) == 1, f"Expected 1 entry_points.txt file, found: {entry_points_files}"
        ep_content = z.read(entry_points_files[0]).decode("utf-8")

        assert "[console_scripts]" in ep_content
        assert "yarvelle-core = yarvelle_core.cli:main" in ep_content

    # 1. Test direct import and invocation of main entrypoint
    from yarvelle_core import __version__
    from yarvelle_core.cli import main
    assert main(["--version"]) == 0

    # 2. Test isolated virtual environment installation and console script invocation
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    pip_bin = venv_dir / "bin" / "pip"
    cli_bin = venv_dir / "bin" / "yarvelle-core"

    install_proc = subprocess.run(
        [str(pip_bin), "install", str(wheel_path), "--no-deps", "--force-reinstall"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert install_proc.returncode == 0, f"pip install failed:\n{install_proc.stderr}"

    cli_proc = subprocess.run(
        [str(cli_bin), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli_proc.returncode == 0, f"yarvelle-core script execution failed:\n{cli_proc.stderr}"
    output = cli_proc.stdout + cli_proc.stderr
    assert f"yarvelle-core {__version__}" in output
