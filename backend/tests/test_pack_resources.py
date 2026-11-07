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


def test_declared_patterns_resource_missing_fails_closed(sample_pack: Path) -> None:
    loader = ResourceLoader()
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
            patterns_resource="resources/does-not-exist.yaml",
        ),
    )
    with pytest.raises(PackResourceError):
        loader.register_pack(pack)


def test_optional_auto_patterns_absent_ok(tmp_path: Path) -> None:
    root = tmp_path / "empty-pack"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.yaml").write_text("id: empty\n", encoding="utf-8")
    (root / "resources").mkdir()
    loader = ResourceLoader()
    pack = PackSpec(
        id="empty",
        name="Empty",
        version="0.0.1",
        domain="empty",
        requires_core=">=0.2.0",
        manifest_path=str(root / "pack.yaml"),
        provides=PackProvidesSpec(),
    )
    resolver = loader.register_pack(pack)
    assert resolver is not None
    # Core patterns still available; no pack overlay keys required.
    patterns = loader.get_routing_patterns()
    assert "generic" in patterns["dossier_types"]


def test_merged_routing_patterns_returns_defensive_copy(sample_pack: Path) -> None:
    loader = ResourceLoader()
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
    loader.register_pack(pack)
    first = loader.get_routing_patterns()
    first["dossier_types"]["generic"] = ["mutated"]
    second = loader.get_routing_patterns()
    assert second["dossier_types"]["generic"] != ["mutated"]


def _register_sample(loader: ResourceLoader, sample_pack: Path, pack_id: str = "sample") -> None:
    pack = PackSpec(
        id=pack_id,
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
    assert loader.register_pack(pack) is not None


def _second_pack(tmp_path: Path) -> Path:
    root = tmp_path / "second-pack"
    _write(
        root / "resources" / "routing_patterns.yaml",
        yaml.safe_dump({"dossier_types": {"second_record": [r"\b(second)\b"]}}),
    )
    _write(root / "pack.yaml", "id: second\n")
    return root


def test_core_dossier_types_unchanged_without_packs() -> None:
    loader = ResourceLoader()
    core_yaml = loader.load_yaml("routing_patterns.yaml")["dossier_types"]
    merged = loader.get_routing_patterns()["dossier_types"]
    assert list(merged) == list(core_yaml)
    assert merged == core_yaml


def test_generic_dossier_type_is_matched_last_with_packs(sample_pack: Path, tmp_path: Path) -> None:
    loader = ResourceLoader()
    core_types = list(loader.load_yaml("routing_patterns.yaml")["dossier_types"])
    _register_sample(loader, sample_pack)
    _register_sample(loader, _second_pack(tmp_path), pack_id="second")

    order = list(loader.get_routing_patterns()["dossier_types"])
    core_specific = [t for t in core_types if t != "generic"]
    # Core-specific types first, then packs in registration order, generic last.
    assert order == core_specific + ["sample_record", "second_record", "generic"]


async def test_summary_query_infers_pack_specific_type(
    sample_pack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langchain_core.messages import HumanMessage

    from yarvelle_core.workflows.subgraphs.extraction import subgraph as extraction_subgraph

    loader = ResourceLoader()
    _register_sample(loader, sample_pack)
    monkeypatch.setattr(extraction_subgraph, "get_resource_loader", lambda: loader)

    seen: dict = {}

    class _FakeExtractTool:
        async def ainvoke(self, args: dict) -> dict:
            seen.update(args)
            return {"dossier": {}, "dossier_type": args["dossier_type"]}

    monkeypatch.setattr(extraction_subgraph, "extract_document_dossier", _FakeExtractTool())

    node = extraction_subgraph.create_extraction_node()
    # "summary" matches core's catch-all generic pattern; the pack's specific
    # type must still win because generic is only a fallback.
    await node({"messages": [HumanMessage(content="Give me a summary of my sample record")], "document_text": "x"})
    assert seen["dossier_type"] == "sample_record"

    seen.clear()
    await node({"messages": [HumanMessage(content="Just a summary please")], "document_text": "x"})
    assert seen["dossier_type"] == "generic"
