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

"""Offline checks that release metadata and the version module stay aligned at 0.2.0."""

from __future__ import annotations

import importlib.metadata
import json
import zipfile
from pathlib import Path

import pytest
import tomllib

import yarvelle_core
from yarvelle_core import version as version_mod

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_version_module_is_020() -> None:
    assert version_mod.__version__ == "0.2.0"
    assert yarvelle_core.__version__ == "0.2.0"
    assert yarvelle_core.__version__ is version_mod.__version__ or yarvelle_core.__version__ == version_mod.__version__


def test_pyproject_and_manifest_agree() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "0.2.0"
    manifest = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == "0.2.0"
    assert importlib.metadata.version("yarvelle-core") == "0.2.0"


def test_release_please_config_targets_v_tags_and_version_file() -> None:
    cfg = json.loads((REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    pkg = cfg["packages"]["backend"]
    assert pkg["version-file"] == "backend/src/yarvelle_core/version.py"
    assert (REPO_ROOT / "backend/src/yarvelle_core/version.py").is_file()
    assert pkg.get("include-component-in-tag") is False
    assert "tag-separator" not in pkg


def test_wheel_metadata_reports_020(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hatchling = pytest.importorskip("hatchling.build")
    backend_root = REPO_ROOT / "backend"
    monkeypatch.chdir(backend_root)
    wheel_name = hatchling.build_wheel(str(tmp_path))
    wheel_path = tmp_path / wheel_name
    assert wheel_path.is_file()
    with zipfile.ZipFile(wheel_path) as zf:
        meta_names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
        assert meta_names
        meta = zf.read(meta_names[0]).decode("utf-8")
        assert "Version: 0.2.0" in meta
        version_members = [n for n in zf.namelist() if n.endswith("yarvelle_core/version.py")]
        assert version_members
        body = zf.read(version_members[0]).decode("utf-8")
        assert '__version__ = "0.2.0"' in body
