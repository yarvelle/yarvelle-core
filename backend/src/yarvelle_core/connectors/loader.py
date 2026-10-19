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

"""Connector registry and dynamic starter loader."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable, Dict, List, Optional

from yarvelle_core.connectors.base import Connector
from yarvelle_core.connectors.errors import ConnectorError
from yarvelle_core.connectors.manifest import ConnectorManifest
from yarvelle_core.connectors.starters.calendar import CalDavConnector, GoogleCalendarConnector

_STARTER_MANIFESTS_DIR = Path(__file__).resolve().parent / "starters" / "manifests"


def _build_starter_factories() -> Dict[str, Callable[[ConnectorManifest], Connector]]:
    factories: Dict[str, Callable[[ConnectorManifest], Connector]] = {
        "google-calendar": lambda manifest: GoogleCalendarConnector(manifest=manifest),
        "caldav": lambda manifest: CalDavConnector(manifest=manifest),
    }
    for pkg_prefix in ("carefold", "carefold_health"):
        try:
            epic_mod = importlib.import_module(f"{pkg_prefix}.connectors.starters.epic_smart")
            withings_mod = importlib.import_module(f"{pkg_prefix}.connectors.starters.withings")
            ehr_mod = importlib.import_module(f"{pkg_prefix}.connectors.starters.ehr_smart_v2")
            wear_mod = importlib.import_module(f"{pkg_prefix}.connectors.starters.wearables_v2")
            zocdoc_mod = importlib.import_module(f"{pkg_prefix}.connectors.starters.zocdoc")
            factories.update({
                "withings": lambda manifest, m=withings_mod: m.WithingsConnector(manifest=manifest),
                "epic-smart": lambda manifest, m=epic_mod: m.EpicSmartConnector(manifest=manifest),
                "zocdoc": lambda manifest, m=zocdoc_mod: m.ZocdocConnector(manifest=manifest),
                "oracle-health": lambda manifest, m=ehr_mod: m.OracleHealthConnector(manifest=manifest),
                "athenahealth": lambda manifest, m=ehr_mod: m.AthenahealthConnector(manifest=manifest),
                "cms-blue-button": lambda manifest, m=ehr_mod: m.CmsBlueButtonConnector(manifest=manifest),
                "oura": lambda manifest, m=wear_mod: m.OuraConnector(manifest=manifest),
                "google-health": lambda manifest, m=wear_mod: m.GoogleHealthConnector(manifest=manifest),
                "microsoft-graph": lambda manifest, m=wear_mod: m.MicrosoftGraphCalendarConnector(manifest=manifest),
            })
            break
        except ImportError:
            continue
    return factories


def _extra_manifest_dirs() -> List[Path]:
    dirs: List[Path] = []
    for pkg_prefix in ("carefold", "carefold_health"):
        try:
            mod = importlib.import_module(f"{pkg_prefix}.connectors.starters")
            if getattr(mod, "__file__", None):
                cand = Path(mod.__file__).resolve().parent / "manifests"
                if cand.is_dir() and cand not in dirs:
                    dirs.append(cand)
        except ImportError:
            continue
    return dirs


_STARTER_MANIFEST_FILES = (
    "withings.yaml",
    "google_calendar.yaml",
    "caldav.yaml",
    "epic_smart.yaml",
)

_V1_STARTER_IDS = frozenset({"withings", "google-calendar", "caldav", "epic-smart"})


class ConnectorRegistry:
    """Registry that discovers, validates, and instantiates starter connectors."""

    def __init__(self, manifests_dir: Optional[Path] = None) -> None:
        self._manifests_dir = manifests_dir or _STARTER_MANIFESTS_DIR
        self._manifests: Dict[str, ConnectorManifest] = {}
        self._factories: Dict[str, Callable[[ConnectorManifest], Connector]] = _build_starter_factories()
        self._discover_builtin_manifests()

    def _discover_builtin_manifests(self) -> None:
        """Loads and validates all starter YAML manifests from disk."""
        search_dirs = [self._manifests_dir]
        if self._manifests_dir == _STARTER_MANIFESTS_DIR:
            search_dirs.extend(_extra_manifest_dirs())

        for filename in _STARTER_MANIFEST_FILES:
            for d in search_dirs:
                manifest_path = d / filename
                if manifest_path.is_file():
                    manifest = ConnectorManifest.from_yaml(manifest_path)
                    self._manifests[manifest.id] = manifest
                    break

        for d in search_dirs:
            if d.is_dir():
                for yaml_path in sorted(d.glob("*.yaml")):
                    manifest = ConnectorManifest.from_yaml(yaml_path)
                    if manifest.id not in self._manifests:
                        self._manifests[manifest.id] = manifest

    def register(
        self,
        manifest: ConnectorManifest,
        factory: Callable[[ConnectorManifest], Connector],
    ) -> None:
        """Registers a connector manifest and its instantiation factory."""
        self._manifests[manifest.id] = manifest
        self._factories[manifest.id] = factory

    def list_manifests(
        self,
        include_mcp: bool = False,
        include_v2: bool = False,
    ) -> List[ConnectorManifest]:
        """Returns registered connector manifests in deterministic order."""
        items = list(self._manifests.values())
        if not include_mcp:
            items = [m for m in items if getattr(m, "kind", "rest") != "mcp"]
        if not include_v2 and self._manifests_dir == _STARTER_MANIFESTS_DIR:
            items = [
                m
                for m in items
                if m.id in _V1_STARTER_IDS
                or (include_mcp and getattr(m, "kind", "rest") == "mcp")
                or m.id not in self._factories
            ]
        return items

    def get_manifest(self, connector_id: str) -> ConnectorManifest:
        """Returns the validated ConnectorManifest for `connector_id`."""
        if connector_id not in self._manifests:
            raise ConnectorError(f"Unknown connector id '{connector_id}'.")
        return self._manifests[connector_id]

    def load(self, connector_id: str) -> Connector:
        """Instantiates and returns the Connector implementation for `connector_id`."""
        manifest = self.get_manifest(connector_id)
        factory = self._factories.get(connector_id)
        if factory is None:
            raise ConnectorError(f"No connector implementation registered for '{connector_id}'.")
        return factory(manifest)


_DEFAULT_REGISTRY: Optional[ConnectorRegistry] = None


def get_connector_registry() -> ConnectorRegistry:
    """Returns the singleton starter ConnectorRegistry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ConnectorRegistry()
    return _DEFAULT_REGISTRY


def list_starter_manifests() -> List[ConnectorManifest]:
    """Returns all built-in starter connector manifests."""
    return get_connector_registry().list_manifests()


def load_connector(connector_id: str) -> Connector:
    """Loads and instantiates a starter connector by its manifest ID."""
    return get_connector_registry().load(connector_id)


__all__ = [
    "ConnectorRegistry",
    "get_connector_registry",
    "list_starter_manifests",
    "load_connector",
]
