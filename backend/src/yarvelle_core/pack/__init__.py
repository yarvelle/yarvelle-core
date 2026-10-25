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

"""Pack API v1 for pluggable domain packs."""

from yarvelle_core.pack.loader import (
    ENTRY_POINT_GROUP,
    LoadedPacksRegistry,
    PackLoadError,
    PackNotFoundError,
    discover_and_load_packs,
)
from yarvelle_core.pack.routing import (
    collect_routing_hints,
    compose_orchestrator_routing_prompt,
)
from yarvelle_core.pack.spec import (
    PackEvalsSpec,
    PackManifest,
    PackMigrationsSpec,
    PackPanelSpec,
    PackProvidesSpec,
    PackSpec,
    PanelDefaultConstraintSpec,
    ReadScopeSpec,
    ScopeDefinitionSpec,
)
from yarvelle_core.pack.validator import (
    LEGACY_TABLE_ALLOWLIST,
    PackValidationError,
    validate_pack_spec,
    validate_pack_yaml_file,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "LoadedPacksRegistry",
    "PackLoadError",
    "PackNotFoundError",
    "discover_and_load_packs",
    "collect_routing_hints",
    "compose_orchestrator_routing_prompt",
    "PackEvalsSpec",
    "PackManifest",
    "PackMigrationsSpec",
    "PackPanelSpec",
    "PackProvidesSpec",
    "PackSpec",
    "PanelDefaultConstraintSpec",
    "ReadScopeSpec",
    "ScopeDefinitionSpec",
    "LEGACY_TABLE_ALLOWLIST",
    "PackValidationError",
    "validate_pack_spec",
    "validate_pack_yaml_file",
]
