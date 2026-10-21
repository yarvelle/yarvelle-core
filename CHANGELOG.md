# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
