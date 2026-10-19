# Contributing to Yarvelle Core

Thank you for your interest in contributing to Yarvelle Core! This repository provides the domain-neutral execution engine, runtime environment, LangGraph multi-agent orchestrator, and `@yarvelle/ui` design system.

---

## Which repo does my change belong in?

The Yarvelle and Carefold ecosystem is organized across three repositories. Before opening a PR or issue, check the table below to make sure your changes belong in `yarvelle-core`:

| Change | Target Repository / Path |
|---|---|
| Engine, safety gate, approvals, scopes, storage, vault, Pack API, connectors SDK, generic API routers | `yarvelle-core/backend` |
| Generic UI component, design token, primitive, chat/notes/calendar/profiles/shell, API client, slot registry | `yarvelle-core/frontend` |
| Manifest JSON Schemas (`pack.schema.json`, `agent.schema.json`, `skill.schema.json`) | `yarvelle-core/schemas` |
| Starter agent/skill templates (`_template/`) and system agents (`_system/`) | `yarvelle-core/agents`, `yarvelle-core/skills` |
| A health specialist agent or clinical skill | `carefold/agents`, `carefold/skills` |
| Health tools, routers, clinical importers, HealthSafetyPolicy, health models/migrations | `carefold/backend/src/carefold_health` |
| Health screens, visit preparation dossiers, and clinical chat renderers | `carefold/frontend/src/health-ui` |
| Carefold application branding, routes, settings pages, and deployment manifests | `carefold/frontend/src/{app,theme}`, `carefold/deploy` |
| Finance, education, or household agents/skills/tools/policies/views | `yarvelle/{agents,skills}`, `yarvelle/backend/src/yarvelle_<pack>`, `yarvelle/frontend/src/<pack>` |
| Yarvelle branding, household shell, and deployment manifests | `yarvelle/frontend/src/{app,theme}`, `yarvelle/deploy` |
| Changes that touch both core and a pack | Land the core change first (released), then the consumer PR that bumps the version |

---

## Development Setup

### Prerequisites
- Python 3.12+ and `uv`
- Node.js 20+ and `pnpm` 12+
- `just` (command runner)

### Initial Setup
```bash
# Clone the repository
git clone https://github.com/spectrayan/yarvelle-core.git
cd yarvelle-core

# Initialize backend and frontend
just dev
```

### Running Tests and Linting
```bash
# Run tests
just test

# Run linters and checks
just lint

# Build artifacts
just build
```

---

## Architectural & Code Purity Rules

1. **Zero Mock Production Policy**: No production code in `backend/src/` or `frontend/src/` may employ fake, dummy, or facade mock implementations.
2. **Domain-Neutrality (GU3)**:
   - Zero clinical or domain-specific keywords (`patient`, `doctor`, `clinical`, `vitals`, `nurse`, `hospital`, etc.) in `yarvelle-core`.
   - Zero hardcoded `#hex` color literals in TypeScript components (use `--ui-*` tokens).
   - Zero raw Tailwind palette classes (`bg-zinc-*`, `text-slate-*`).
   - Zero `dark:` class overrides (theme is resolved via CSS variables).
   - Zero physical-direction classes (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-` only).
3. **Packaging Invariant**: Content in `agents/`, `skills/`, and `schemas/` is force-included into the Python wheel under `yarvelle_core/_content/` via `backend/hatch_build.py`.
4. **License Headers**: Every `.py`, `.ts`, `.tsx`, `.js`, and `.mjs` file must contain the official Spectrayan PolyForm Noncommercial copyright header.
