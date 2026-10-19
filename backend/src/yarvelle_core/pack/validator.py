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
from typing import Collection, List, Optional, Set, Union
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from yarvelle_core.pack.spec import PackManifest, PackSpec
from yarvelle_core.scope.context import matches_scope

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


def validate_pack_spec(spec: PackSpec, core_version: Optional[str] = None) -> None:
    """Semantically validates a runtime PackSpec instance.

    Args:
        spec: The PackSpec instance to validate.
        core_version: Optional current yarvelle_core version to check against requires_core.

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

    if errors:
        raise PackValidationError(spec.id, errors)


def validate_pack_yaml_file(yaml_path: Union[str, Path], core_version: Optional[str] = None) -> PackManifest:
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

    if errors:
        raise PackValidationError(manifest.id, errors)

    return manifest
