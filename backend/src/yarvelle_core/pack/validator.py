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

"""Pack semantic validator enforcing multi-domain safety and isolation rules."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Collection, List, Optional, Set, Union
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from yarvelle_core.pack.spec import CrossPackGrantSpec, PackManifest, PackPanelSpec, PackSpec
from yarvelle_core.scope.context import matches_scope


def _extract_active_grants(
    spec: Union[PackSpec, PackManifest],
    panel: PackPanelSpec,
    runtime_grants: Optional[Collection[str]] = None,
) -> Set[str]:
    """Collects all authorized foreign pack slugs and domain prefixes for a panel."""
    grants: Set[str] = set()

    # 1. Pack-level grants
    pack_grants = getattr(spec, "cross_pack_grants", None) or []
    for g in pack_grants:
        if isinstance(g, str):
            grants.add(g.strip().lower())
        elif isinstance(g, CrossPackGrantSpec):
            if not g.panels or panel.id in g.panels:
                grants.add(g.pack.strip().lower())
        elif isinstance(g, dict):
            pack_name = g.get("pack", "")
            panels = g.get("panels", [])
            if not panels or panel.id in panels:
                grants.add(pack_name.strip().lower())

    # 2. Panel-level grants
    panel_grants = getattr(panel, "cross_pack_grants", None) or []
    for g in panel_grants:
        if isinstance(g, str):
            grants.add(g.strip().lower())

    # 3. Runtime grants
    if runtime_grants:
        for rg in runtime_grants:
            grants.add(rg.strip().lower())

    return grants


def _is_cross_pack_agent_permitted(
    spec: Union[PackSpec, PackManifest],
    panel: PackPanelSpec,
    ag_id: str,
    foreign_identifier: str,
    active_grants: Set[str],
) -> bool:
    """Verifies whether a foreign-domain/pack agent is authorized by active grants."""
    if not (
        "*" in active_grants
        or foreign_identifier.lower() in active_grants
        or ag_id.lower() in active_grants
    ):
        return False

    # Check if a CrossPackGrantSpec imposes agent-level restrictions
    pack_grants = getattr(spec, "cross_pack_grants", None) or []
    restricted = False
    allowed_by_agent_spec = False
    for g in pack_grants:
        if isinstance(g, CrossPackGrantSpec):
            if g.pack.strip().lower() == foreign_identifier.lower():
                if not g.panels or panel.id in g.panels:
                    if g.agents:
                        restricted = True
                        if ag_id in g.agents or ag_id.split(".")[-1] in g.agents or ag_id.split(":")[-1] in g.agents:
                            allowed_by_agent_spec = True
        elif isinstance(g, dict):
            p_name = g.get("pack", "").strip().lower()
            if p_name == foreign_identifier.lower():
                p_panels = g.get("panels", [])
                if not p_panels or panel.id in p_panels:
                    p_agents = g.get("agents", [])
                    if p_agents:
                        restricted = True
                        if ag_id in p_agents or ag_id.split(".")[-1] in p_agents or ag_id.split(":")[-1] in p_agents:
                            allowed_by_agent_spec = True

    if restricted:
        return allowed_by_agent_spec
    return True

LEGACY_TABLE_ALLOWLIST: Set[str] = frozenset({
    "appointments",
    "preventive_records",
    "import_batches",
    "school_forms",
    "school_ics_feeds",
    "companion_devices",
    "health_resources",
})


class PackValidationError(ValueError):
    """Raised when a pack manifest or specification fails semantic validation."""

    def __init__(self, pack_id: str, errors: List[str]) -> None:
        self.pack_id = pack_id
        self.errors = errors
        formatted = "\n  - ".join(errors)
        super().__init__(f"Pack '{pack_id}' failed semantic validation:\n  - {formatted}")


def validate_pack_spec(
    spec: PackSpec,
    core_version: Optional[str] = None,
    runtime_grants: Optional[Collection[str]] = None,
) -> None:
    """Semantically validates a runtime PackSpec instance.

    Args:
        spec: The PackSpec instance to validate.
        core_version: Optional current yarvelle_core version to check against requires_core.
        runtime_grants: Optional collection of authorized cross-pack domain slugs / patterns.

    Raises:
        PackValidationError: If any safety, scope, or metadata invariant is violated.
    """
    errors: List[str] = []

    # 1. Validate SemVer formats
    try:
        Version(spec.version)
    except InvalidVersion:
        errors.append(f"Invalid pack version '{spec.version}': must be a valid SemVer/PEP440 string.")

    try:
        specifier = SpecifierSet(spec.requires_core)
        if core_version is not None:
            parsed_core = Version(core_version)
            if parsed_core not in specifier:
                errors.append(
                    f"Core version '{core_version}' is incompatible with pack requires_core '{spec.requires_core}'."
                )
    except InvalidSpecifier:
        errors.append(f"Invalid requires_core specifier '{spec.requires_core}'.")

    # 2. Rule 1: Validate owned_scopes prefix matches pack domain
    for scope in spec.owned_scopes:
        clean_scope = scope.rstrip(".*")
        if clean_scope != spec.domain and not clean_scope.startswith(f"{spec.domain}."):
            errors.append(
                f"Owned scope '{scope}' does not match pack domain '{spec.domain}'. "
                f"All owned scopes must be prefixed with '{spec.domain}.' or equal '{spec.domain}.*'."
            )

    # 3. Rule 2: Validate tool scopes belong to owned_scopes
    for tool in spec.tools:
        tool_scopes = getattr(tool, "scopes", set()) or set()
        for t_scope in tool_scopes:
            if not any(matches_scope(owned, t_scope) for owned in spec.owned_scopes):
                errors.append(
                    f"Tool '{tool.name}' declares scope '{t_scope}' which is not in pack owned_scopes "
                    f"{spec.owned_scopes}."
                )

    # 4. Rule 3: Validate declared_reads don't collide with owned_scopes
    for read_scope in spec.declared_reads:
        if any(matches_scope(owned, read_scope) or matches_scope(read_scope, owned) for owned in spec.owned_scopes):
            errors.append(
                f"Declared read scope '{read_scope}' collides with owned scopes {spec.owned_scopes}. "
                "A pack cannot declare cross-domain reads on its own scopes."
            )

    # 5. Rule 4: Validate T2+ packs declare evals
    if spec.risk_tier_max in ("T2", "T3", "T4"):
        has_evals = False
        if spec.evals is not None and (spec.evals.golden_path or spec.evals.eval_suites):
            has_evals = True
        if not has_evals:
            errors.append(
                f"Pack declares risk_tier_max='{spec.risk_tier_max}' (T2+) but does not provide an evals specification. "
                "All T2+ packs must declare golden evaluation datasets."
            )

    # 6. Rule 5: Validate ORM table prefixes match pack domain
    for model in spec.scoped_models:
        tablename = getattr(model, "__tablename__", None)
        if tablename:
            is_legacy = tablename in LEGACY_TABLE_ALLOWLIST and spec.domain == "health"
            valid_prefix = tablename.startswith(f"{spec.domain}_") or tablename.startswith(f"{spec.id}_")
            if not is_legacy and not valid_prefix:
                errors.append(
                    f"Model '{model.__name__}' specifies table '{tablename}' which does not start with "
                    f"'{spec.domain}_' or '{spec.id}_'."
                )

    # 7. Rule 7: Multi-Agent Deliberation Panel Validation (ADR 0001 §2.9, §7 Phase 3)
    all_panels = list(spec.panels)
    if getattr(spec, "provides", None) and spec.provides.panels:
        for p in spec.provides.panels:
            if p not in all_panels:
                all_panels.append(p)

    for panel in all_panels:
        if len(panel.agents) < 2:
            errors.append(f"Panel '{panel.id}' must specify at least 2 agents, got {len(panel.agents)}.")
        if len(panel.agents) != len(set(panel.agents)):
            errors.append(f"Panel '{panel.id}' contains duplicate agents: {panel.agents}.")
        if panel.max_rounds < 1 or panel.max_rounds > 4:
            errors.append(f"Panel '{panel.id}' max_rounds must be between 1 and 4, got {panel.max_rounds}.")

        for constraint in panel.default_constraints:
            if not re.match(r"^[a-z0-9_-]{1,64}$", constraint.id):
                errors.append(f"Panel '{panel.id}' constraint '{constraint.id}' is not a valid slug.")

        # Determine authorized grants for this panel
        active_grants = _extract_active_grants(spec, panel, runtime_grants)

        # Check declared scopes if provided
        if getattr(panel, "scopes", None):
            for sc in panel.scopes:
                scope_prefix = sc.split(".")[0] if "." in sc else sc
                is_owned = any(matches_scope(owned, sc) for owned in spec.owned_scopes)
                is_declared_read = any(matches_scope(read, sc) for read in getattr(spec, "declared_reads", []))
                is_granted = scope_prefix in active_grants or "*" in active_grants or sc in active_grants
                if not (is_owned or is_declared_read or is_granted):
                    errors.append(
                        f"Panel '{panel.id}' declares scope '{sc}' not in pack owned_scopes {spec.owned_scopes}, "
                        f"declared_reads, or authorized cross_pack_grants {sorted(active_grants)}."
                    )

            domain_prefixes = {s.split(".")[0] for s in panel.scopes if "." in s}
            foreign_domains = {
                p for p in domain_prefixes
                if p != spec.domain and not any(matches_scope(owned, f"{p}.*") for owned in spec.owned_scopes)
            }
            for fd in foreign_domains:
                if fd not in active_grants and "*" not in active_grants:
                    errors.append(
                        f"Panel '{panel.id}' spans foreign domain scope prefix '{fd}' without an explicit cross-pack grant. "
                        f"Cross-pack panels require explicit grants in cross_pack_grants or runtime configuration (ADR 0001 §2.9)."
                    )

        # Check agent domain ownership & cross-pack grants
        for ag_id in panel.agents:
            is_native = False
            foreign_identifier: Optional[str] = None

            if getattr(spec, "agents", None) and spec.agents:
                if ag_id in spec.agents:
                    is_native = True
                else:
                    if "." in ag_id:
                        foreign_identifier = ag_id.split(".")[0]
                    elif ":" in ag_id:
                        foreign_identifier = ag_id.split(":")[0]
                    else:
                        foreign_identifier = ag_id
            else:
                if "." in ag_id:
                    prefix = ag_id.split(".")[0]
                    if prefix == spec.domain or any(matches_scope(owned, f"{prefix}.*") for owned in spec.owned_scopes):
                        is_native = True
                    else:
                        foreign_identifier = prefix
                elif ":" in ag_id:
                    prefix = ag_id.split(":")[0]
                    if prefix == spec.domain or prefix == spec.id:
                        is_native = True
                    else:
                        foreign_identifier = prefix
                else:
                    is_native = True

            if not is_native and foreign_identifier:
                if not _is_cross_pack_agent_permitted(spec, panel, ag_id, foreign_identifier, active_grants):
                    errors.append(
                        f"Panel '{panel.id}' contains cross-pack/cross-domain agent '{ag_id}' outside pack '{spec.id}', "
                        f"but no explicit cross-pack grant was found for '{foreign_identifier}'. "
                        f"Cross-pack panel membership requires an explicit grant in cross_pack_grants or runtime configuration (ADR 0001 §2.9)."
                    )

    if errors:
        raise PackValidationError(spec.id, errors)


def validate_pack_yaml_file(
    yaml_path: Union[str, Path],
    core_version: Optional[str] = None,
    runtime_grants: Optional[Collection[str]] = None,
) -> PackManifest:
    """Reads and semantically validates a pack.yaml file from disk.

    Returns:
        Validated PackManifest instance.
    """
    path = Path(yaml_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"pack.yaml file not found at: {path}")

    raw_text = path.read_text(encoding="utf-8")
    parsed_dict = yaml.safe_load(raw_text)
    if not isinstance(parsed_dict, dict):
        raise ValueError(f"pack.yaml at {path} does not contain a valid YAML dictionary.")

    manifest = PackManifest.model_validate(parsed_dict)

    # Perform semantic cross-field checks
    errors: List[str] = []

    # Check SemVer
    try:
        specifier = SpecifierSet(manifest.requires_core)
        if core_version is not None and Version(core_version) not in specifier:
            errors.append(
                f"Core version '{core_version}' does not satisfy pack requires_core '{manifest.requires_core}'."
            )
    except InvalidSpecifier:
        errors.append(f"Invalid requires_core '{manifest.requires_core}'.")

    # Scope prefixes
    for s_def in manifest.scopes:
        clean = s_def.id.rstrip(".*")
        if clean != manifest.domain and not clean.startswith(f"{manifest.domain}."):
            errors.append(
                f"Scope '{s_def.id}' does not match domain '{manifest.domain}'."
            )

    # Declared reads collision
    owned_ids = [s.id for s in manifest.scopes]
    for r_def in manifest.reads:
        if any(matches_scope(o, r_def.id) for o in owned_ids):
            errors.append(
                f"Declared read scope '{r_def.id}' collides with owned scope in {owned_ids}."
            )

    # Evals for T2+
    if manifest.risk_tier_max in ("T2", "T3", "T4"):
        evals_path = manifest.provides.evals if manifest.provides else None
        if not evals_path:
            errors.append(
                f"Pack declares risk_tier_max='{manifest.risk_tier_max}' but provides.evals is missing."
            )

    # Deliberation panels validation (ADR 0001 §2.9, §7 Phase 3)
    if manifest.provides and manifest.provides.panels:
        read_ids = [r.id for r in manifest.reads]
        for panel in manifest.provides.panels:
            if len(panel.agents) < 2:
                errors.append(f"Panel '{panel.id}' must specify at least 2 agents, got {len(panel.agents)}.")
            if len(panel.agents) != len(set(panel.agents)):
                errors.append(f"Panel '{panel.id}' contains duplicate agents: {panel.agents}.")
            if panel.max_rounds < 1 or panel.max_rounds > 4:
                errors.append(f"Panel '{panel.id}' max_rounds must be between 1 and 4, got {panel.max_rounds}.")
            for constraint in panel.default_constraints:
                if not re.match(r"^[a-z0-9_-]{1,64}$", constraint.id):
                    errors.append(f"Panel '{panel.id}' constraint '{constraint.id}' is not a valid slug.")

            active_grants = _extract_active_grants(manifest, panel, runtime_grants)

            if getattr(panel, "scopes", None):
                for sc in panel.scopes:
                    scope_prefix = sc.split(".")[0] if "." in sc else sc
                    is_owned = any(matches_scope(owned, sc) for owned in owned_ids)
                    is_declared_read = any(matches_scope(read, sc) for read in read_ids)
                    is_granted = scope_prefix in active_grants or "*" in active_grants or sc in active_grants
                    if not (is_owned or is_declared_read or is_granted):
                        errors.append(
                            f"Panel '{panel.id}' declares scope '{sc}' not in pack owned_scopes {owned_ids}, "
                            f"declared_reads, or authorized cross_pack_grants {sorted(active_grants)}."
                        )

                domain_prefixes = {s.split(".")[0] for s in panel.scopes if "." in s}
                foreign_domains = {
                    p for p in domain_prefixes
                    if p != manifest.domain and not any(s_id.startswith(f"{p}.") or s_id == f"{p}.*" for s_id in owned_ids)
                }
                for fd in foreign_domains:
                    if fd not in active_grants and "*" not in active_grants:
                        errors.append(
                            f"Panel '{panel.id}' spans foreign domain scope prefix '{fd}' without an explicit cross-pack grant. "
                            f"Cross-pack panels require explicit grants in cross_pack_grants or runtime configuration (ADR 0001 §2.9)."
                        )

            for ag_id in panel.agents:
                is_native = False
                foreign_identifier: Optional[str] = None
                if "." in ag_id:
                    prefix = ag_id.split(".")[0]
                    if prefix == manifest.domain or any(s_id.startswith(f"{prefix}.") or s_id == f"{prefix}.*" for s_id in owned_ids):
                        is_native = True
                    else:
                        foreign_identifier = prefix
                elif ":" in ag_id:
                    prefix = ag_id.split(":")[0]
                    if prefix == manifest.domain or prefix == manifest.id:
                        is_native = True
                    else:
                        foreign_identifier = prefix
                else:
                    is_native = True

                if not is_native and foreign_identifier:
                    if not _is_cross_pack_agent_permitted(manifest, panel, ag_id, foreign_identifier, active_grants):
                        errors.append(
                            f"Panel '{panel.id}' contains cross-pack/cross-domain agent '{ag_id}' outside pack domain '{manifest.domain}', "
                            f"but no explicit cross-pack grant was found for '{foreign_identifier}'. "
                            f"Cross-pack panel membership requires an explicit grant in cross_pack_grants or runtime configuration (ADR 0001 §2.9)."
                        )

    if errors:
        raise PackValidationError(manifest.id, errors)

    return manifest
