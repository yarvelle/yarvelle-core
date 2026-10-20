# Yarvelle Core

**Domain-Neutral AI Agent Runtime, Execution Engine & Multi-Domain Scope Isolation Framework**  
Copyright 2026 Spectrayan (https://spectrayan.com)

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) and the [Yarvelle Core Additional Terms](ADDITIONAL-TERMS.md).

---

## Overview

`yarvelle-core` is the domain-neutral execution backbone of the Yarvelle ecosystem. It provides:
1. **Deterministic Agent Runtime**: LangGraph state machine execution, tool execution gating, agent reflection, and contextual follow-up generation.
2. **Pack API v1**: Pluggable domain pack architecture (`pack.yaml`, `PackSpec`) allowing external packs to register specialized tools, routers, safety policies, and database models.
3. **11-Layer Scope Isolation Engine**: Strict multi-domain data isolation (`ScopeContext`, `ScopedSession`, partitioned CAS storage, scoped FTS5 lexical search, memory namespace partitioning, and HKDF-derived vault sub-keys).
4. **Local-First Security & Cryptography**: Envelope encryption keyring vault (PBKDF2/Argon2 KEK, AES-256-GCM DEK), audit hash chaining, and localhost-bound API server.
5. **Conformance Test Suite**: Comprehensive verification framework (`yarvelle_core.conformance`) asserting zero cross-domain leakage across all 11 security layers.

## Architecture

Dependencies flow strictly inward:
```
Applications (Carefold, Yarvelle) ──► Domain Packs (Health, Finance, Kids) ──► Yarvelle Core
```
`yarvelle_core` contains zero domain-specific business logic or terminology.

## Installation

```bash
pip install yarvelle-core
```

For development:
```bash
git clone https://github.com/yarvelle/yarvelle-core.git
cd yarvelle-core
pip install -e ".[dev]"
```

## Running Verification

```bash
# Run unit & isolation tests
pytest tests/

# Verify layer ordering and package boundaries
lint-imports

# Verify zero domain words in core
pytest tests/test_neutral_words_scan.py
```
