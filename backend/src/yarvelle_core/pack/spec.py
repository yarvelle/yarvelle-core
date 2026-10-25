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

"""Pack API v1 data models and runtime specifications."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

from yarvelle_core.engine.safety_policy import SafetyPolicy
from yarvelle_core.engine.tool_registry import ToolSpec
from yarvelle_core.schemas.routing import RoutingHints


@dataclass
class RouterContribution:
    """API router contributed by core or a domain pack.

    Pack contributions (any pack_id other than "core") must declare ``scope``;
    core mounts them behind ``require_pack_scope(scope, level)`` so every route
    is authenticated and scope-checked (02 §3, §4.2). ``prefix`` is relative
    to the API root (e.g. "/finance/accounts", never "/api/v1/...").
    """

    router: Any
    prefix: str = ""
    tags: Optional[List[Union[str, Any]]] = None
    dependencies: Optional[Sequence[Any]] = None
    include_in_schema: bool = True
    pack_id: Optional[str] = None
    scope: Optional[str] = None
    level: Optional[str] = None
    require_profile: bool = True


SLUG_REGEX = re.compile(r"^[a-z0-9_-]+$")
SCOPE_ID_REGEX = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_*-]+)*$")
SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+([a-zA-Z0-9_.-]*)$")

RiskTierMax = Literal["T1", "T2", "T3", "T4"]


class ScopeDefinitionSpec(BaseModel):
    """Specification of a scope owned by a pack."""

    id: str = Field(..., description="Unique scope identifier e.g. 'health.records', 'finance.accounts'")
    description: str = Field(default="", description="Human-readable description of data protected by this scope")
    consent: Literal["required", "optional"] = Field(
        default="optional", description="Whether explicit user consent is required before first write"
    )
    sensitivity: Literal["public", "internal", "confidential", "phi", "pii"] = Field(
        default="internal", description="Data sensitivity classification driving encryption and egress policies"
    )

    @field_validator("id")
    @classmethod
    def validate_scope_id(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SCOPE_ID_REGEX.match(clean):
            raise ValueError(f"Invalid scope id '{v}': must match {SCOPE_ID_REGEX.pattern}")
        return clean


class ReadScopeSpec(BaseModel):
    """Specification of a cross-domain scope read by a pack."""

    id: str = Field(..., description="Scope identifier of another pack e.g. 'household.calendar'")
    level: Literal["read", "write", "approve"] = Field(default="read", description="Requested access level")
    purpose: str = Field(default="", description="Functional purpose for requesting cross-scope access")
    optional: bool = Field(default=True, description="Whether the pack can function if this grant is not given")

    @field_validator("id")
    @classmethod
    def validate_scope_id(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SCOPE_ID_REGEX.match(clean):
            raise ValueError(f"Invalid read scope id '{v}': must match {SCOPE_ID_REGEX.pattern}")
        return clean


class PackEvalsSpec(BaseModel):
    """Specification of golden and red-team evals declared by a pack."""

    golden_path: Optional[str] = Field(default=None, description="Path to golden eval dataset e.g. 'evals/golden.jsonl'")
    red_team_path: Optional[str] = Field(default=None, description="Path to red-team eval dataset for T2+ packs")
    min_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0, description="Minimum passing threshold")
    eval_suites: List[str] = Field(default_factory=list, description="Declared evaluation suite identifiers")


class PackMigrationsSpec(BaseModel):
    """Specification of Alembic database migration branch contributed by a pack."""

    branch: str = Field(..., description="Alembic branch label e.g. 'health', 'finance', 'kids'")
    version_table: str = Field(..., description="Dedicated version tracking table e.g. 'alembic_version_health'")
    location: Optional[str] = Field(default=None, description="Relative directory containing migration revisions")
    depends_on_core: str = Field(default="core@0010", description="Earliest core schema revision required")


class PanelDefaultConstraintSpec(BaseModel):
    """Specification of default constraint declared by a panel."""

    id: str = Field(..., pattern=r"^[a-z0-9_-]{1,64}$", description="Constraint slug identifier")
    description: str = Field(default="", description="Human-readable description of constraint")
    unit: str = Field(..., description="Measurement unit matching closed unit registry")


class PackPanelSpec(BaseModel):
    """Specification of a multi-agent deliberation panel in a pack."""

    id: str = Field(..., pattern=r"^[a-z0-9_-]{1,64}$", description="Panel slug identifier")
    title: str = Field(..., description="Display title for the panel")
    description: str = Field(default="", description="Purpose and objective of the panel")
    agents: List[str] = Field(..., min_length=2, description="Specialist agent IDs participating in the panel")
    max_rounds: int = Field(default=2, ge=1, le=4, description="Deliberation round limit (default 2)")
    default_constraints: List[PanelDefaultConstraintSpec] = Field(
        default_factory=list, description="Default shared constraints for this panel"
    )
    scopes: List[str] = Field(
        default_factory=list, description="Domain scopes participating in the panel (single scope in Phase 1)"
    )


class PackProvidesSpec(BaseModel):
    """Declarative manifest entries contributed by a pack on disk."""

    agents_dir: Optional[str] = Field(default="agents/", description="Directory containing agent definitions")
    skills_dir: Optional[str] = Field(default="skills/", description="Directory containing skill definitions")
    tools: List[Dict[str, Any]] = Field(default_factory=list, description="Declared tool contribution entries")
    routers: List[Dict[str, Any]] = Field(default_factory=list, description="Declared API router contribution entries")
    jobs: List[Dict[str, Any]] = Field(default_factory=list, description="Declared scheduled job handlers")
    safety_policy: Optional[str] = Field(default=None, description="Import path to SafetyPolicy implementation")
    routing: Optional[Dict[str, Any]] = Field(default=None, description="Declarative domain routing hints")
    prompts_dir: Optional[str] = Field(default="resources/prompts/", description="Prompt templates directory")
    locales_dir: Optional[str] = Field(default="resources/locales/", description="Locale message bundles directory")
    connectors_dir: Optional[str] = Field(default="connectors/", description="Connector manifests directory")
    evals: Optional[str] = Field(default=None, description="Path to evals definition or dataset")
    panels: List[PackPanelSpec] = Field(default_factory=list, description="Declared multi-agent deliberation panels contributed by this pack")


class PackManifest(BaseModel):
    """Pydantic model representing a pack.yaml manifest file on disk."""

    model_config = ConfigDict(extra="forbid")

    pack_api: int = Field(default=1, description="Pack API specification version integer")
    id: str = Field(..., description="Unique brand-neutral pack slug e.g. 'health', 'finance', 'kids'")
    name: str = Field(..., description="Display name of the pack")
    version: str = Field(..., description="SemVer string of this pack version")
    domain: str = Field(..., description="Primary domain identifier (e.g. 'health', 'finance', 'education', 'household')")
    requires_core: str = Field(..., description="PEP 440 / SemVer range for yarvelle-core e.g. '>=0.1.0,<0.2.0'")
    requires_packs: List[Dict[str, str]] = Field(default_factory=list, description="Dependencies on other packs")
    license: Optional[str] = Field(default=None, description="License expression")
    maintainers: List[str] = Field(default_factory=list, description="Maintainer usernames or teams")
    risk_tier_max: RiskTierMax = Field(default="T2", description="Highest risk tier permitted for any action")
    scopes: List[ScopeDefinitionSpec] = Field(default_factory=list, description="Scopes owned by this pack")
    reads: List[ReadScopeSpec] = Field(default_factory=list, description="Scopes of other packs requested for reading")
    provides: Optional[PackProvidesSpec] = Field(default_factory=PackProvidesSpec, description="Contributed runtime artifacts")
    migrations: Optional[PackMigrationsSpec] = Field(default=None, description="Database migration branch spec")
    compat: Optional[Dict[str, Any]] = Field(default=None, description="Compatibility metadata")

    @field_validator("id")
    @classmethod
    def validate_id_slug(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SLUG_REGEX.match(clean):
            raise ValueError(f"Pack id '{v}' must be a lowercase alphanumeric slug matching {SLUG_REGEX.pattern}")
        return clean

    @field_validator("domain")
    @classmethod
    def validate_domain_slug(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SLUG_REGEX.match(clean):
            raise ValueError(f"Domain '{v}' must be a lowercase alphanumeric slug matching {SLUG_REGEX.pattern}")
        return clean


class PackSpec(BaseModel):
    """Runtime contract exposed by a pack entry point (get_pack() -> PackSpec)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    pack_api: int = Field(default=1, description="Pack API version integer")
    id: str = Field(..., description="Unique pack slug e.g. 'health', 'finance', 'kids'")
    name: str = Field(..., description="Display name of the pack")
    version: str = Field(..., description="SemVer version string of the pack")
    domain: str = Field(..., description="Primary domain e.g. 'health', 'finance', 'education'")
    requires_core: str = Field(..., description="PEP 440 version range for yarvelle-core e.g. '>=0.1.0,<0.2.0'")
    owned_scopes: List[str] = Field(default_factory=list, description="Scope patterns owned by this pack e.g. ['health.*']")
    declared_reads: List[str] = Field(default_factory=list, description="Scopes owned by other packs this pack reads")
    risk_tier_max: RiskTierMax = Field(default="T2", description="Maximum risk tier permitted ('T1', 'T2', 'T3', 'T4')")
    tools: List[ToolSpec] = Field(default_factory=list, description="Registered ToolSpec instances")
    routers: List[RouterContribution] = Field(default_factory=list, description="Registered API RouterContribution instances")
    safety_policy: Optional[SafetyPolicy] = Field(default=None, description="SafetyPolicy implementation for this domain")
    migration_branch: Optional[str] = Field(default=None, description="Alembic migration branch name")
    evals: Optional[PackEvalsSpec] = Field(default=None, description="Evaluations specification")
    description: str = Field(default="", description="Pack overview description")
    license: Optional[str] = Field(default=None, description="License identifier")
    maintainers: List[str] = Field(default_factory=list, description="Maintainers list")
    routing_hints: Optional[RoutingHints] = Field(default=None, description="Dynamic routing hints for orchestrator")
    scoped_models: List[Any] = Field(default_factory=list, description="SQLAlchemy model classes extending ScopedMixin")
    jobs: List[Any] = Field(default_factory=list, description="Job handlers contributed by the pack")
    manifest_path: Optional[str] = Field(default=None, description="Filesystem path to source pack.yaml")
    panels: List[PackPanelSpec] = Field(default_factory=list, description="Registered multi-agent deliberation panels")
    provides: Optional[PackProvidesSpec] = Field(default=None, description="Optional provides specification")
    agents: List[str] = Field(default_factory=list, description="Agent identifiers contributed by this pack")

    @field_validator("id", "domain")
    @classmethod
    def validate_slugs(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SLUG_REGEX.match(clean):
            raise ValueError(f"Value '{v}' must be a lowercase slug matching {SLUG_REGEX.pattern}")
        return clean


PackSpec.model_rebuild()
