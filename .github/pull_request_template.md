## Description

<!-- Provide a concise explanation of what this PR introduces, modifies, or fixes. -->

## Motivation and Context

<!-- Why is this change needed? What problem does it solve? If it fixes an open issue, link it here: e.g. Fixes #123 -->

## Type of Change

<!-- Mark the appropriate box with an [x] -->
- [ ] `feat`: New runtime capability, system agent, tool, or `@yarvelle/ui` component
- [ ] `fix`: Bug fix, scope isolation patch, or sandbox hardening
- [ ] `docs`: Documentation updates or new Architecture Decision Record (ADR)
- [ ] `refactor`: Code refactoring without behavioral change
- [ ] `perf`: Performance, query planning, or hybrid search improvement
- [ ] `test`: New unit, conformance, adversarial, or component tests
- [ ] `chore`: Maintenance, schema regeneration, dependency, or CI/CD update

## Pre-Merge Verification Checklist

<!-- Please confirm all of the following checks pass locally prior to requesting review: -->

- [ ] **Developer Certificate of Origin (DCO)**: All commits are signed off (`git commit -s`).
- [ ] **Conventional Commits**: Commit messages follow `<type>(<scope>): <description>`.
- [ ] **License & Dependency Checks**: All modified or new `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, `.css` files contain the official Spectrayan PolyForm Noncommercial + Yarvelle Core Additional Terms copyright header, and no git dependencies exist:
  - Verified with: `python3 scripts/check_licenses.py && python3 scripts/check_no_git_deps.py`
- [ ] **Domain Neutrality ("Core Knows No Domain")**: Zero health, clinical, financial, or domain-specific vocabulary introduced in `backend/` or `frontend/`:
  - Verified with: `PYTHONPATH=backend/src uv run --project backend pytest backend/tests/test_neutral_words_scan.py`
- [ ] **Import Boundary Linter**: Architectural layer boundaries are intact:
  - Verified with: `cd backend && PYTHONPATH=src uv run lint-imports`
- [ ] **Backend Test Suite**: All unit, integration, 11-layer conformance, and adversarial tests pass:
  - Verified with: `PYTHONPATH=backend/src uv run --project backend pytest backend/tests/`
- [ ] **Frontend (`@yarvelle/ui`) Quality & Build**:
  - TypeScript check: `pnpm --dir frontend run typecheck`
  - Token lint, RTL, contrast & unit tests: `pnpm --dir frontend test`
  - Production package build: `pnpm --dir frontend run build`
- [ ] **Scope Isolation & Security Invariants**:
  - `ScopeContext` isolation, `declared_reads` + runtime grant checks, `TaintFlag` propagation, and `SqlAstSandbox` invariants preserved.
- [ ] **Schemas & Documentation**:
  - Canonical JSON schemas synchronized (`python3 scripts/generate_schemas.py`) if `PackSpec`, `AgentManifest`, or `SkillManifest` changed.
  - Living ADRs in `docs/adr/` updated and verified with `mkdocs build --strict`.
