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

"""Secure pack-native resource resolver and ResourceLoader pack overlays."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yarvelle_core.pack.spec import PackProvidesSpec, PackSpec
from yarvelle_core.resources.loader import ResourceLoader
from yarvelle_core.resources.pack_resolver import (
    PackResourceError,
    PackResourceResolver,
)
from yarvelle_core.schemas.routing import RoutingHints


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def sample_pack(tmp_path: Path) -> Path:
    root = tmp_path / "sample-pack"
    _write(
        root / "resources" / "routing_patterns.yaml",
        yaml.safe_dump(
            {
                "dossier_types": {
                    "sample_record": [r"\b(sample|record)\b"],
                    "generic": [r"\b(should_not_override)\b"],
                },
                "domain_keywords": {"sample": ["sample"]},
                "routing_rules": [{"id": "sample-rule"}],
            }
        ),
    )
    _write(root / "resources" / "prompts" / "extraction" / "sample_record.md", "Extract a sample record.")
    _write(root / "workflows" / "patterns.yaml", "name: sample\n")
    _write(root / "pack.yaml", "id: sample\n")
    return root


def test_resolve_allows_resources_and_workflows(sample_pack: Path) -> None:
    resolver = PackResourceResolver("sample", sample_pack)
    assert resolver.resolve_path("resources/routing_patterns.yaml").is_file()
    assert resolver.resolve_path("workflows/patterns.yaml").is_file()
    data = resolver.load_yaml("resources/routing_patterns.yaml")
    assert "sample_record" in data["dossier_types"]


@pytest.mark.parametrize(
    "bad",
    [
        "../secret.yaml",
        "resources/../../etc/passwd",
        "/etc/passwd",
        "file:///etc/passwd",
        "src/code.py",
        "resources/note.py",
    ],
)
def test_resolve_refuses_traversal_absolute_and_disallowed(sample_pack: Path, bad: str) -> None:
    resolver = PackResourceResolver("sample", sample_pack)
    with pytest.raises(PackResourceError):
        resolver.resolve_path(bad)


def test_resolve_refuses_null_byte(sample_pack: Path) -> None:
    resolver = PackResourceResolver("sample", sample_pack)
    with pytest.raises(PackResourceError):
        resolver.resolve_path("resources/rou\x00ting.yaml")


def test_symlink_escape_refused(sample_pack: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text("secret: 1\n", encoding="utf-8")
    link = sample_pack / "resources" / "escape.yaml"
    link.symlink_to(outside)
    resolver = PackResourceResolver("sample", sample_pack)
    with pytest.raises(PackResourceError):
        resolver.resolve_path("resources/escape.yaml")


def test_size_limit(sample_pack: Path) -> None:
    big = sample_pack / "resources" / "big.yaml"
    big.write_bytes(b"x" * 2048)
    resolver = PackResourceResolver("sample", sample_pack, max_bytes=1024)
    with pytest.raises(PackResourceError):
        resolver.read_bytes("resources/big.yaml")


def test_missing_file(sample_pack: Path) -> None:
    resolver = PackResourceResolver("sample", sample_pack)
    with pytest.raises(FileNotFoundError):
        resolver.read_text("resources/missing.yaml")


def test_resource_loader_merges_pack_overlay_without_overriding_core(sample_pack: Path) -> None:
    loader = ResourceLoader()
    core_before = loader.get_routing_patterns()
    assert "generic" in core_before.get("dossier_types", {})
    core_generic = list(core_before["dossier_types"]["generic"])

    pack = PackSpec(
        id="sample",
        name="Sample",
        version="0.0.1",
        domain="sample",
        requires_core=">=0.2.0",
        manifest_path=str(sample_pack / "pack.yaml"),
        provides=PackProvidesSpec(),
        routing_hints=RoutingHints(
            domain="sample",
            description="Sample domain",
            default_agent="sample-agent",
            patterns_resource="resources/routing_patterns.yaml",
        ),
    )
    resolver = loader.register_pack(pack)
    assert resolver is not None
    merged = loader.get_routing_patterns()
    assert merged["dossier_types"]["generic"] == core_generic
    assert "sample_record" in merged["dossier_types"]
    assert "sample" in merged["domain_keywords"]
    assert any(r.get("id") == "sample-rule" for r in merged["routing_rules"])
    assert loader.load_pack_yaml("sample", "resources/routing_patterns.yaml")["dossier_types"]["sample_record"]
    assert "sample record" in loader.get_pack_prompt_text(
        "sample", "resources/prompts/extraction/sample_record.md"
    ).lower()


def test_core_resource_loader_still_loads_disclaimers() -> None:
    loader = ResourceLoader()
    data = loader.get_disclaimers()
    assert isinstance(data, dict)
    assert data  # bundled core resources remain available
