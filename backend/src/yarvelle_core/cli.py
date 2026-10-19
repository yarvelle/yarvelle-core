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

"""Yarvelle Core Command Line Interface (CLI)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence

from yarvelle_core import __version__


def _run_verify(strict: bool = False) -> int:
    """Verifies runtime environment, bundled assets, and installed packs."""
    try:
        from yarvelle_core.config import settings
        from yarvelle_core.pack.loader import discover_and_load_packs
    except ImportError as err:
        print(f"Error loading dependencies: {err}")
        return 1

    print(f"Yarvelle Core v{__version__} Environment Verification")
    print("-" * 52)

    workspace_root = settings.workspace_root
    agents_dir = settings.get_agents_dir()
    skills_dir = settings.get_skills_dir()

    print(f"Workspace Root:    {workspace_root} (exists: {workspace_root.is_dir()})")
    print(f"Agents Directory:  {agents_dir} (exists: {agents_dir.is_dir()})")
    print(f"Skills Directory:  {skills_dir} (exists: {skills_dir.is_dir()})")

    # Discover installed domain packs
    try:
        registry = discover_and_load_packs()
        pack_count = len(registry.packs)
        print(f"Discovered Packs:  {pack_count}")
        for pid, pack in registry.packs.items():
            print(f"  - {pid} (v{pack.version}): {pack.name} [domain: {pack.domain}]")
    except Exception as err:
        print(f"Discovered Packs:  ERROR ({err})")
        if strict:
            return 1

    if strict and (not agents_dir.is_dir() or not skills_dir.is_dir()):
        print("Verification: FAILED (missing required directory in strict mode)")
        return 1

    print("-" * 52)
    print("Environment verification: PASSED")
    return 0


def _run_packs() -> int:
    """Lists all discovered domain packs and their contributed scopes."""
    try:
        from yarvelle_core.pack.loader import discover_and_load_packs
    except ImportError as err:
        print(f"Error loading dependencies: {err}")
        return 1

    print(f"Yarvelle Core v{__version__} Discovered Packs")
    print("-" * 52)
    try:
        registry = discover_and_load_packs()
        if not registry.packs:
            print("No domain packs currently installed in Python environment.")
            return 0
        for pid, pack in registry.packs.items():
            print(f"Pack: {pid} (v{pack.version})")
            print(f"  Name:   {pack.name}")
            print(f"  Domain: {pack.domain}")
            print(f"  Scopes: {', '.join(sorted(pack.owned_scopes))}")
    except Exception as err:
        print(f"Error discovering packs: {err}")
        return 1
    return 0


def _run_info() -> int:
    """Prints runtime configuration paths and active settings."""
    try:
        from yarvelle_core.config import settings
    except ImportError as err:
        print(f"Error loading dependencies: {err}")
        return 1

    print(f"Yarvelle Core v{__version__} Runtime Info")
    print("-" * 52)
    print(f"Product Name:    {settings.product_name}")
    print(f"Core Version:    {__version__}")
    print(f"Python:          {sys.version.split()[0]}")
    print(f"Workspace Root:  {settings.workspace_root}")
    print(f"Home Directory:  {settings.home_dir}")
    print(f"Agents Dir:      {settings.get_agents_dir()}")
    print(f"Skills Dir:      {settings.get_skills_dir()}")
    print(f"Auth Provider:   {settings.auth_provider}")
    print(f"Default Model:   {settings.default_model}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI entry point for yarvelle-core console script."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="yarvelle-core",
        description=f"Yarvelle Core {__version__} — Domain-Neutral AI Agent Runtime & Execution Engine",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"yarvelle-core {__version__}",
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify environment configuration, bundled assets, and installed packs",
    )
    verify_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any required component or directory is missing",
    )

    # packs command
    subparsers.add_parser(
        "packs",
        help="List discovered and registered domain packs",
    )

    # info command
    subparsers.add_parser(
        "info",
        help="Display runtime configuration and environment paths",
    )

    # help command
    subparsers.add_parser(
        "help",
        help="Show this help message and exit",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if args.command == "verify":
        return _run_verify(strict=args.strict)
    elif args.command == "packs":
        return _run_packs()
    elif args.command == "info":
        return _run_info()
    elif args.command == "help":
        parser.print_help()
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
