# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-10-29

### Added
- **Multi-Agent Blackboard Deliberation (`ExecutionMode.DELIBERATE`)**: Added bounded scoped blackboard deliberation engine (`Propose -> CrossExamine -> ConvergenceGate -> SelectiveRevise -> Synthesize & Gate`) with `TypedClaim` cross-domain exports, Disagree-or-Commit peer review, deterministic `SharedConstraint` budget auditing, universal human approval on panel-staged actions (`Approval.agent_id`), live deliberation SSE events, and `@yarvelle/ui` `DeliberationRoundtable` / `RoundtableCard` components (`workflows.deliberation`, `ADR-0001`).
- **Dynamic Multi-Dialect MCP Database Toolbox & `db-operator`**: Added M-Schema `SchemaCatalog` introspection, 5-stage `sqlglot` AST sandbox (`SELECT`, `INSERT`, `UPDATE`, `DELETE` with parenthesized `profile_id` + `scope` tenant predicate injection and strict DDL/DCL/TCL rejection across SQLite, PostgreSQL, MySQL/MariaDB, SQL Server, and DuckDB), dynamic tools (`db_inspect_schema`, `db_execute_query`, `db_mutate_records`), declarative `db_tools.yaml` registry, and the `db-operator` system agent (`db.schema_catalog`, `tools.sql_ast_sandbox`, `tools.mcp_db_toolbox`, `ADR-0002`).
- **Living Architecture Decision Records & Docs Site**: Migrated core ADRs (`0000`–`0011`), added `AGENTS.md` v1.0.0 manifest, GitHub PR/issue templates, and MkDocs Material GitHub Pages publishing.

### Fixed
- **Pack Database Tool Hooks & Cache Invalidation**: Committed write-hook sessions on mutation completion, forwarded `ToolContext` as `_ctx` to registered pack hooks, invalidated cached toolboxes on `register_db_tools_yaml`, and resolved pack-declared `<domain>_<risk>_db` toolsets in `get_toolset_for_domain` (`tools.mcp_db_toolbox`).

## [0.1.1] - 2026-10-21

### Added
- **CORS Allowlist & Bind Guard**: Added `build_cors_options` with validated explicit origin, method, and header allowlists, and `enforce_bind_safety` to prevent unauthenticated non-loopback binds (`api.cors`).
- **Pack Router Scope Guard**: Added `require_pack_scope` and automatic guard mounting on non-core `RouterContribution` routes with profile ownership and `ScopeGrant` level enforcement (`api.scope_guard`).
- **Untrusted Tool Output Fencing**: Added `wrap_tool_output` with per-call randomized boundary markers and data-only standing notices for tool results passed to the model (`engine.untrusted_content`).

### Fixed
- **Approval Argument Redaction**: Masked credential-like keys, bearer tokens, JWTs, private keys, and API keys at rest and in streamed approval events via `redact_tool_args` (`audit.redaction`).
- **Approval Profile & Tool Binding**: Bound `consume_approval_atomic` verification to `profile_id` and `tool_name` in addition to payload hash (`engine.approvals`).
- **Policy Gate Fail-Closed & Age Bands**: Enforced fail-closed approval requirement on unknown or missing tool risk tiers and canonicalized age bands (`child_under_13`, `teen_13_17`, `adult`, `older_adult`) (`engine.policy_gate`, `schemas.age_band`).
- **CAS Partition Isolation**: Enforced fail-closed owner partition resolution in `sanitize_partition_segment` and `resolve_user_partition` so owner-less requests in multi-user mode raise `CasPartitionError` (`storage.cas`).
- **Atomic Profile Deletion**: Refactored `delete_profile` to purge all `profile_id`-scoped mapped tables and DEK rows atomically before filesystem, memory, and search cleanup (`api.profiles`).
- **Shared Profile Access Lookup**: Fixed missing `sqlalchemy.select` import in `get_user_profile_access` (`api.deps`).
- **Connector Tool Context Resolution**: Lazily resolved `ConnectorToolContext` to avoid import-order circularity (`engine`).

## [0.1.0] - 2026-10-19

### Added
- **Backend Restructure**: Organized python runtime into `backend/` with Hatchling build system.
- **Content Packaging**: Implemented dynamic Hatchling build hook (`backend/hatch_build.py`) force-including `agents/`, `skills/`, and `schemas/` into wheels under `yarvelle_core/_content/`.
- **System Agents & Templates**: Ingested domain-neutral system agents (`orchestrator`, `document-extractor`, `skill-generator`, `suggestion-generator`) and starter templates (`agents/_template`, `skills/_template`).
- **UI Context & Preferences**: Added `ProfileUiPreference` model and `GET /api/v1/me/ui-context`, `GET/PUT /api/v1/me/profiles/{profile_id}/ui-prefs` endpoints.
- **Pack UI Specification**: Added `PackUiSpec` and `PackA2UiSpec` with slot contributions and A2UI schema blocks.
- **@yarvelle/ui Design System**:
  - W3C DTCG design tokens with light and dark semantic palettes emitting `--ui-*` CSS variables.
  - 10 domain-neutral component modules: primitives, chat, notes, calendar, profiles, tasks, notifications, settings, shell, and slots/provider/lib.
  - Full RTL logical property enforcement (zero physical direction classes).
  - Strict GU3 compliance: zero `#hex` in components, zero raw palette classes, zero `dark:` variants, zero domain keywords.
- **Governance & CI**: Added root `justfile`, `compat.yaml`, release-please, changesets, and GitHub Actions CI matrix.
