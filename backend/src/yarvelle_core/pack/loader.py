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

"""Entry-point discovery and pack registration loader (importlib.metadata)."""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from yarvelle_core import __version__ as CORE_VERSION
from yarvelle_core.engine.safety_policy import SafetyPolicy, set_domain_safety_policy
from yarvelle_core.engine.tool_registry import ToolSpecRegistry, bound_declarative_to_tool_spec
from yarvelle_core.pack.spec import PackSpec, RouterContribution
from yarvelle_core.pack.validator import validate_pack_spec
from yarvelle_core.resources.loader import get_resource_loader
from yarvelle_core.tools.spec_loader import get_tool_spec_loader

logger = logging.getLogger("yarvelle_core.pack.loader")
ENTRY_POINT_GROUP = "yarvelle.packs"


class PackNotFoundError(Exception):
    """Raised when an enabled pack cannot be discovered in entry points."""
    pass


class PackLoadError(Exception):
    """Raised when an entry point fails to load or return a valid PackSpec."""
    pass


class LoadedPacksRegistry:
    """Registry maintaining active loaded PackSpec instances and aggregated contributions."""

    def __init__(self) -> None:
        self.packs: Dict[str, PackSpec] = {}
        self.tool_registry: ToolSpecRegistry = ToolSpecRegistry()
        self.router_contributions: List[RouterContribution] = []
        self.safety_policies: Dict[str, SafetyPolicy] = {}
        self.migration_branches: Dict[str, str] = {}
        self.scoped_models: List[Any] = []

    def get_pack(self, pack_id: str) -> Optional[PackSpec]:
        return self.packs.get(pack_id)

    def is_pack_loaded(self, pack_id: str) -> bool:
        return pack_id in self.packs

    def get_all_owned_scopes(self) -> Set[str]:
        scopes = set()
        for p in self.packs.values():
            scopes.update(p.owned_scopes)
        return scopes


def discover_and_load_packs(
    enabled_pack_ids: Optional[Sequence[str]] = None,
    tool_registry: Optional[ToolSpecRegistry] = None,
    core_version: str = CORE_VERSION,
) -> LoadedPacksRegistry:
    """Discovers and registers packs contributed via the 'yarvelle.packs' entry point group.

    Args:
        enabled_pack_ids: List of pack slugs enabled by configuration (e.g. ['health', 'finance']).
                          If None, all discovered packs are loaded.
        tool_registry: Target ToolSpecRegistry to receive contributed tools.
        core_version: yarvelle_core version to enforce against requires_core.

    Returns:
        LoadedPacksRegistry populated with validated packs and aggregated contributions.
    """
    registry = LoadedPacksRegistry()
    if tool_registry is not None:
        registry.tool_registry = tool_registry

    # 1. Query entry points
    try:
        discovered_eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        # Fallback for Python < 3.10
        all_eps = importlib.metadata.entry_points()
        discovered_eps = all_eps.get(ENTRY_POINT_GROUP, [])

    eps_by_name = {ep.name: ep for ep in discovered_eps}

    target_ids = list(enabled_pack_ids) if enabled_pack_ids is not None else list(eps_by_name.keys())

    # 2. Check for missing enabled packs
    for req_id in target_ids:
        if req_id not in eps_by_name:
            raise PackNotFoundError(
                f"Enabled pack '{req_id}' is not installed or did not register an entry point "
                f"in group '{ENTRY_POINT_GROUP}'. Discovered packs: {list(eps_by_name.keys())}"
            )

    # 3. Load, validate, and register each pack
    for pack_id in target_ids:
        ep = eps_by_name[pack_id]
        logger.info(f"Loading pack '{pack_id}' from entry point: {ep.value}")

        try:
            pack_factory = ep.load()
            if not callable(pack_factory):
                raise TypeError(f"Pack entry point '{ep.value}' is not callable.")
            pack_spec: PackSpec = pack_factory()
            if not isinstance(pack_spec, PackSpec):
                raise TypeError(
                    f"Pack entry point '{ep.value}' returned '{type(pack_spec).__name__}', expected PackSpec."
                )
        except Exception as err:
            raise PackLoadError(f"Failed to load pack '{pack_id}': {err}") from err

        # Verify semantic invariants
        validate_pack_spec(pack_spec, core_version=core_version)

        # Propagate pack root from the entry-point module's pack.yaml when present.
        if not getattr(pack_spec, "manifest_path", None):
            try:
                mod = importlib.import_module(pack_factory.__module__)
                mod_file = getattr(mod, "__file__", None)
                if mod_file:
                    candidate = Path(mod_file).resolve().parent / "pack.yaml"
                    if candidate.is_file():
                        pack_spec = pack_spec.model_copy(update={"manifest_path": str(candidate)})
            except Exception:
                pass

        # Register tools (explicit Python ToolSpecs + declarative YAML/JSON specs if present)
        for tool in pack_spec.tools:
            registry.tool_registry.register(tool, pack_id=pack_spec.id)

        if getattr(pack_spec, "manifest_path", None):
            pack_root = Path(str(pack_spec.manifest_path)).resolve().parent
            decl_loader = get_tool_spec_loader()
            for candidate_rel in ("resources/tools", "tools.yaml", "resources/tools.yaml"):
                candidate_path = pack_root / candidate_rel
                if candidate_path.exists():
                    try:
                        decl_loader.register_pack_source(pack_spec.id, candidate_path)
                        for bound in decl_loader.load_pack_tools(pack_spec.id):
                            if registry.tool_registry.get(bound.spec.name) is None:
                                registry.tool_registry.register(
                                    bound_declarative_to_tool_spec(bound),
                                    pack_id=pack_spec.id,
                                )
                    except Exception as tool_err:
                        raise PackLoadError(
                            f"Pack '{pack_spec.id}' declarative tool registration failed: {tool_err}"
                        ) from tool_err

        # Register router contributions
        for router_contrib in pack_spec.routers:
            router_contrib.pack_id = pack_spec.id
            registry.router_contributions.append(router_contrib)

        # Wrap the safety policy with the pack's guard checks (safety.guards).
        # Invalid guard configuration fails the load instead of running unguarded.
        guards = pack_spec.safety.guards if pack_spec.safety is not None else None
        if guards is not None and (guards.checks or guards.release == "buffered"):
            from yarvelle_core.engine.guards import build_guarded_policy
            from yarvelle_core.engine.safety_policy import NeutralSafetyPolicy

            try:
                guarded = build_guarded_policy(
                    pack_spec.safety_policy or NeutralSafetyPolicy(),
                    guards,
                    pack=pack_spec,
                    include_env=False,
                )
            except Exception as err:
                raise PackLoadError(f"Invalid safety.guards in pack '{pack_id}': {err}") from err
            pack_spec = pack_spec.model_copy(update={"safety_policy": guarded})

        # Register safety policy
        if pack_spec.safety_policy is not None:
            registry.safety_policies[pack_spec.domain] = pack_spec.safety_policy
            set_domain_safety_policy(pack_spec.domain, pack_spec.safety_policy)

        # Register migration branch
        if pack_spec.migration_branch:
            registry.migration_branches[pack_spec.id] = pack_spec.migration_branch

        # Register scoped models
        registry.scoped_models.extend(pack_spec.scoped_models)

        registry.packs[pack_spec.id] = pack_spec
        try:
            get_resource_loader().register_pack(pack_spec)
        except Exception as res_err:
            # Missing pack root (no manifest_path) is optional; declared/invalid
            # resource paths must fail closed as PackLoadError.
            from yarvelle_core.resources.pack_resolver import PackResourceError

            if isinstance(res_err, PackResourceError):
                raise PackLoadError(
                    f"Pack '{pack_spec.id}' resource registration failed: {res_err}"
                ) from res_err
            raise PackLoadError(
                f"Pack '{pack_spec.id}' resource registration failed: {res_err}"
            ) from res_err
        logger.info(
            f"Successfully loaded and registered pack '{pack_spec.id}' v{pack_spec.version} "
            f"with {len(pack_spec.tools)} tools, {len(pack_spec.routers)} routers."
        )

    return registry
