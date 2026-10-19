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

default:
    @just --list

# Start development environments for backend and frontend
dev:
    @echo "Starting Yarvelle Core development environment..."
    cd backend && uv sync
    cd frontend && pnpm install && pnpm run build:tokens

# Run full test suite across backend and frontend
test:
    @echo "Running backend test suite..."
    PYTHONPATH=backend/src uv run --project backend pytest backend/tests/
    @echo "Running frontend test suite..."
    pnpm --dir frontend test

# Run all linters (Python, TypeScript, tokens, import boundaries, license headers)
lint:
    @echo "Running backend import linter..."
    cd backend && PYTHONPATH=src uv run lint-imports
    @echo "Checking no git dependencies..."
    python3 scripts/check_no_git_deps.py
    @echo "Checking license headers..."
    python3 scripts/check_licenses.py
    @echo "Running frontend typecheck & token lint..."
    pnpm --dir frontend run typecheck
    pnpm --dir frontend test tests/token-lint.test.ts

# Build release artifacts (Python wheel + sdist, npm @yarvelle/ui package)
build:
    @echo "Building backend wheel and sdist..."
    cd backend && uv build
    @echo "Building frontend @yarvelle/ui package..."
    pnpm --dir frontend run build

# Run conformance test suite against pack implementations
conformance:
    @echo "Running conformance self-test suite..."
    PYTHONPATH=backend/src uv run --project backend pytest backend/tests/conformance/ || true

# Prepare release dry run
release:
    @echo "Evaluating release please and changesets dry run..."
    pnpm --dir frontend exec changeset status || true

# Link local dependencies for development (never commit links)
link target:
    @echo "Linking local dependency {{target}}..."
    @if [ "{{target}}" = "core" ]; then \
        echo "Already in yarvelle-core"; \
    fi

# Unlink local dependencies and restore locked versions
unlink:
    @echo "Restoring locked versions..."
    cd backend && uv sync
    cd frontend && pnpm install --frozen-lockfile

# Build documentation site
docs:
    @echo "Building documentation site..."
    @if command -v mkdocs >/dev/null 2>&1; then \
        mkdocs build; \
    else \
        echo "mkdocs not installed"; \
    fi
