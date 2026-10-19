# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
