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

"""Tests for Yarvelle Core CLI (yarvelle_core.cli:main)."""

from __future__ import annotations

import subprocess
import sys
import pytest

from yarvelle_core import __version__
from yarvelle_core.cli import main
from yarvelle_core.schemas.manifest import AgentDomain, RiskClass


@pytest.fixture(autouse=True)
def isolate_extensible_registries():
    """Snapshots and restores extensible enum registries to prevent cross-test leakage from discovered packs."""
    saved_domains = dict(AgentDomain._registry)
    saved_risks = dict(RiskClass._registry)
    try:
        yield
    finally:
        AgentDomain._registry.clear()
        AgentDomain._registry.update(saved_domains)
        RiskClass._registry.clear()
        RiskClass._registry.update(saved_risks)


def test_cli_version(capsys):
    """Verifies that --version and -V output correct version string and exit cleanly."""
    exit_code = main(["--version"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert f"yarvelle-core {__version__}" in captured.out or f"yarvelle-core {__version__}" in captured.err

    exit_code_short = main(["-V"])
    assert exit_code_short == 0


def test_cli_help(capsys):
    """Verifies that --help, help command, and no arguments display help and return 0."""
    assert main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "usage: yarvelle-core" in captured.out

    assert main(["help"]) == 0
    captured_help = capsys.readouterr()
    assert "usage: yarvelle-core" in captured_help.out

    assert main([]) == 0
    captured_empty = capsys.readouterr()
    assert "usage: yarvelle-core" in captured_empty.out


def test_cli_verify(capsys):
    """Verifies that verify subcommand executes environment checks and returns 0."""
    exit_code = main(["verify"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Environment Verification" in captured.out
    assert "Environment verification: PASSED" in captured.out


def test_cli_verify_strict(capsys):
    """Verifies that verify --strict runs without error in configured workspace."""
    exit_code = main(["verify", "--strict"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Environment verification: PASSED" in captured.out


def test_cli_packs(capsys):
    """Verifies that packs subcommand inspects entry points and returns 0."""
    exit_code = main(["packs"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Discovered Packs" in captured.out


def test_cli_info(capsys):
    """Verifies that info subcommand prints configuration and returns 0."""
    exit_code = main(["info"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Runtime Info" in captured.out
    assert f"Core Version:    {__version__}" in captured.out


def test_cli_invalid_options(capsys):
    """Verifies that invalid arguments return non-zero exit code."""
    exit_code = main(["--totally-unrecognized-flag"])
    assert exit_code != 0


def test_cli_subprocess_module():
    """Verifies that executing python -m yarvelle_core.cli succeeds in a subprocess."""
    proc = subprocess.run(
        [sys.executable, "-m", "yarvelle_core.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert f"yarvelle-core {__version__}" in output
