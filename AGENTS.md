# Yarvelle Core Autonomous Agent Manifest

<!--
  Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
  Copyright 2026 Spectrayan (https://spectrayan.com)

  Licensed under the PolyForm Noncommercial License 1.0.0 and the
  Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
  Personal and household local use only. Commercial use, hosted service
  offering, rebranding, white-labeling, and redistribution of modified
  forks are prohibited without a written commercial license from Spectrayan.

  Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
-->

Specification compliance: [AGENTS.md v1.0.0](https://github.com/agent-infra/agents.md)  
Runtime version: Yarvelle Core 0.1.1  
Last updated: 2026-10-25  

---

## 1. Project Boundaries & Operational Constraints

`yarvelle-core` is the domain-neutral AI agent runtime, multi-agent deliberation engine, 11-layer scope isolation framework, and shared UI component library (`@yarvelle/ui`) that powers downstream domain-specific applications (such as `carefold` and `yarvelle`) via pluggable domain packs (`PackSpec` / `pack.yaml`).

### 1.1 Strict Domain-Neutrality Mandate ("Core Knows No Domain")
- **Inward Dependency Flow Only**:
  ```
  Applications (Carefold, Yarvelle) ──► Domain Packs ──► Yarvelle Core
  ```
  `yarvelle-core` never imports a domain pack or application package.
- **Zero Domain Vocabulary**: No health, clinical, therapy, medical, financial, tax, debt, or other domain-specific business logic, keyword lists, prompt templates, unit assumptions, UI labels, or test fixtures may exist anywhere in `backend/src/`, `backend/tests/`, `frontend/src/`, or `frontend/tests/`.
- **Programmatic Enforcement**: Domain neutrality is continuously verified by `backend/tests/test_neutral_words_scan.py`. All domain-specific agents, skills, routing hints, safety policies, and panels belong exclusively in external domain packs.

### 1.2 Local-First Security, Scope Isolation & Human-in-the-Loop (HITL) Policy
- **11-Layer Scope Isolation Engine**: Every execution turn and tool call runs inside an explicit `ScopeContext` (`scope_context`). Data access is isolated across `ScopedSession` database queries, per-profile/per-scope Content-Addressed Storage (CAS), scoped FTS5 + vector hybrid search, memory namespace partitioning, and HKDF-SHA256 derived AES-256-GCM vault keys. Cross-scope reads require both a pack-declared `declared_reads` entry and an active runtime grant, and emit tamper-evident SHA-256 hash-chained `scope.cross_read` audit events.
- **4-Tier Tool Execution Gate & Monotone Taint**: Tools are classified into `read`, `write_local`, `write_external`, or `irreversible` (`KNOWN_RISK_TIERS` in `engine/tool_exec.py`), gated by autonomy level (`A0`–`A3`), monotone taint propagation (`TaintFlag` / `UntrustedResult`), consent, and age band. Unrecognized tools or risk tiers fail closed to `irreversible`.
- **Universal Approval for Panel-Staged Actions**: During multi-agent deliberation (`ExecutionMode.DELIBERATE`), direct write tools are blocked in `Propose` and `SelectiveRevise` rounds. Any `StagedAction` proposed by a panel forces human approval before execution regardless of risk tier (`write_local`, `write_external`, `irreversible`) or autonomy level (`A0`–`A3`), with single-use cryptographic binding to `(agent_id, tool_name, profile_id, canonical_json(tool_args))`.
- **Non-Prescriptive Advisory Framing**: Synthesized outputs act as cognitive preparation aids for human review and must pass through `OutputGuardrailNode` evaluating the union of participating packs' `SafetyPolicy` rules (`UnionSafetyPolicy`).

---

## 2. System Architecture & Topology

The `yarvelle-core` repository is structured as a polyglot monorepo containing the Python backend runtime (`yarvelle-core`) and the TypeScript/React design-system & chat UI library (`@yarvelle/ui`):

```
yarvelle-core/
├── backend/                        # FastAPI + LangGraph domain-neutral execution runtime
│   ├── src/yarvelle_core/
│   │   ├── agents/                 # Agent manifest models & registry loaders
│   │   ├── api/                    # FastAPI v1 routers (chat, agents, skills, approvals, audit, auth, memory)
│   │   ├── audit/                  # Tamper-evident SHA-256 hash-chained audit_events & PII redaction
│   │   ├── auth/                   # Argon2 password hashing, session tokens & localhost bind guard
│   │   ├── companion/              # Paired companion sync protocol abstractions
│   │   ├── conformance/            # 11-layer multi-domain isolation conformance suite & PackProtocol
│   │   ├── connectors/             # OAuth 2.0 PKCE broker, ScopedHttp allowlisting & UntrustedResult taint
│   │   ├── constants/              # Canonical API routes, HTTP status codes & SSE event names (api.py)
│   │   ├── db/                     # SQLAlchemy 2.0 async declarative models & Alembic migrations
│   │   ├── engine/                 # GraphBuilder, AgentExecutionService, 4-tier tool_exec gate & UnionSafetyPolicy
│   │   ├── i18n/                   # BCP 47 / RFC 4647 locale negotiation, UAX #15 NFC & ICU catalogs
│   │   ├── loaders/                # Sandboxed agent, skill, and resource manifest loaders
│   │   ├── memory/                 # Hexagonal ports (MemoryPort, CatalogPort) & scoped SQLite FTS5 adapters
│   │   ├── model/                  # Multi-provider LLM abstraction (Ollama, Anthropic, OpenAI, Google)
│   │   ├── pack/                   # Pack API v1 (PackSpec, PackProvidesSpec, PanelSpec & validator)
│   │   ├── schemas/                # Pydantic v2 schemas (ExecutionPlan, DeliberationConfig, Audit, Routing)
│   │   ├── scope/                  # ScopeContext, ScopedSession & cross-scope access enforcement
│   │   ├── search/                 # Hybrid SearchIndex (FTS5 + sqlite-vec, RRF, MMR & local reranker)
│   │   ├── storage/                # Partitioned Content-Addressed Storage (CAS)
│   │   ├── tools/                  # Sandboxed file, attachment, extraction, and delegation tools
│   │   ├── vault/                  # Envelope encryption keyring vault (HKDF-SHA256 AES-256-GCM DEKs)
│   │   └── workflows/              # LangGraph state machine, dispatcher, nodes & deliberation engine
│   │       ├── deliberation/       # Bounded blackboard deliberation (ADR-0001: propose, doc_critique, auditor, gate, revise, tool_gate, subgraph, engine)
│   │       └── nodes/              # InputGuardrail, Orchestrator, AgentExecution, Tool, ResponseSynthesizer, OutputGuardrail, Suggestion, Refusal
│   └── tests/                      # Pytest unit, integration, conformance, adversarial & golden eval suites
├── frontend/                       # @yarvelle/ui React 19 + Tailwind CSS token-driven component library
│   ├── src/
│   │   ├── calendar/               # Generic scheduling & timeline primitives
│   │   ├── chat/                   # Chat, ExecutionPlanCard, DeliberationRoundtable, RoundtableCard, ApprovalCard, ToolTraceCard
│   │   ├── lib/                    # Formatting, cn utilities & helpers
│   │   ├── notes/                  # Workspace note components
│   │   ├── notifications/          # Toast & alert primitives
│   │   ├── primitives/             # Accessible UI primitives (Button, Badge, Card, Dialog, Tabs, Tooltip)
│   │   ├── profiles/               # Multi-profile switcher & consent components
│   │   ├── provider/               # Theme, locale & direction (LTR/RTL) providers
│   │   ├── settings/               # Runtime, model & autonomy settings views
│   │   ├── shell/                  # Application layout shell & navigation
│   │   ├── slots/                  # Extensible pack UI slot registry
│   │   ├── tasks/                  # Task & checklist components
│   │   └── tokens/                 # Design tokens (CSS custom properties, zero raw color/direction leaks)
│   └── tests/                      # Vitest component, token-lint, contrast, a11y/RTL & roundtable test suites
├── agents/                         # System agents (_system/) and starter agent template (_template/)
├── skills/                         # Starter skill pack template (_template/)
├── schemas/                        # Canonical JSON Schemas (pack.schema.json, agent.schema.json, skill.schema.json)
├── scripts/                        # License checkers, git-dep validator & JSON schema generator
└── docs/
    └── adr/                        # Living Architecture Decision Records (0000–0011)
```

### 2.1 Execution Topologies (`ExecutionMode` in `schemas/plan.py`)

`yarvelle-core` supports four deterministic execution topologies dispatched by `ExecutionDispatcher`:

| Mode | Value | Execution Semantics |
| :--- | :--- | :--- |
| `SINGLE` | `"single"` | Single specialist agent handles the user turn with up to `DEFAULT_MAX_ITERATIONS` tool loops. |
| `PARALLEL` | `"parallel"` | Multiple independent specialists run concurrently via `asyncio.gather`. |
| `PIPELINE` | `"pipeline"` | Topologically sorted DAG where downstream agents receive `# PRIOR SPECIALIST OUTPUTS` as read-only context. |
| `DELIBERATE` | `"deliberate"` | Bounded, multi-round scoped blackboard deliberation (`Propose -> CrossExamine -> ConvergenceGate -> SelectiveRevise -> Synthesize & Gate`) per [ADR 0001](docs/adr/0001-multi-agent-deliberation.md). |

### 2.2 System Agents (`agents/_system/`)

1. **`orchestrator`**: Complexity-tiered intent routing (`SINGLE`, `PARALLEL`, `PIPELINE`, `DELIBERATE`), declarative routing-hint confirmation, and dynamic skill/panel provisioning.
2. **`document-extractor`**: Sandboxed attachment ingestion, PII sanitization, structured Pydantic dossier extraction, and numerical grounding verification.
3. **`skill-generator`**: Synthesis of dynamic skill manifests and validation templates from reference guidelines.
4. **`suggestion-generator`**: Context-aware follow-up suggestion chips emitted over SSE.
5. **`db-operator`**: Dynamic SQL query planner and deterministic AST-sandboxed executor (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) across any SQL dialect per [ADR 0002](docs/adr/0002-dynamic-mcp-db-toolbox.md).

### 2.3 Multi-Agent Blackboard Deliberation ([ADR 0001](docs/adr/0001-multi-agent-deliberation.md))

- **Scoped Blackboard (`workflows/deliberation/blackboard.py`)**: Deliberation state resides in a dedicated `deliberation_state` channel on `AgentState` (`TypedClaim`, `StagedAction`, `AgentProposal`, `PeerCritique`). Same-domain panels read full peer proposals; cross-domain panels export only schema-validated `TypedClaim` records (`SLUG_REGEX` keys and closed `ALLOWED_CLAIM_UNITS`), gated by `declared_reads` + grants and logged via hash-chained `scope.cross_read` audit events.
- **Disagree-or-Commit (`workflows/deliberation/doc_critique.py`)**: Reviewers must either commit with a concrete supporting point (`ENDORSE` / `COMPLEMENT`) or raise a typed objection (`AMEND` / `CONFLICT`) across `per_agent` (default) or `batched` (local-model) critique modes.
- **Deterministic Constraint Budget Auditor (`workflows/deliberation/auditor.py`)**: Sums `resource_claims` per `SharedConstraint` against user- or profile-sourced `limit_value` (`limit_source` in `{"user", "profile"}`), raising `resource_overbudget` `CONFLICT` critiques on overruns and failing closed on unit mismatches.
- **Rule-Based Convergence & Selective Revision (`workflows/deliberation/gate.py`, `revise.py`)**: Enters `SelectiveRevise` when open `CONFLICT` or `AMEND` critiques exist and budget/rounds remain; re-runs only targeted specialists. Self-reported `confidence` never drives convergence.
- **Live SSE Streaming & `@yarvelle/ui` Roundtable**: Emits `panel_start`, `deliberation_proposal`, `deliberation_critique`, `deliberation_revision`, and `deliberation_end` custom events rendered by `DeliberationRoundtable` (`frontend/src/chat/DeliberationRoundtable.tsx`).

---

## 3. Agent Toolsets & Sandbox Security

Agents interact with the environment exclusively through registered, sandboxed tools defined in `backend/src/yarvelle_core/tools/`.

### 3.1 Core Tool Registry
- **`attach-read`**: Sandboxed reading of user-uploaded files in `attachments/` with strict protection against path traversal (`../`), null bytes, and symlink escapes.
- **`workspace-note`**: Reading and writing ephemeral notes in `workspace/notes/`.
- **`skill-docs`**: Authorized access to reference guidelines declared on the agent's manifest; undeclared skill reads are blocked immediately.
- **`delegate_to_agent`**: Inter-agent routing controlled by the orchestrator.
- **`list_agents`**: Querying `CatalogPort` for registered specialist agents.
- **`sanitize_pii`**: Redacts sensitive personal identifiers prior to extraction or external model calls.
- **`extract_structured_data`** / **`validate_grounding`** / **`extract_document_dossier`**: Structured Pydantic extraction and numerical grounding validation against source text.
- **`db_inspect_schema`** / **`db_execute_query`** / **`db_mutate_records`**: Dynamic M-Schema database introspection, parameterized `SELECT` query planning/execution, and AST-sandboxed `INSERT` / `UPDATE` / `DELETE` mutations (`tools/mcp_db_toolbox.py`, `tools/sql_ast_sandbox.py`, `db/schema_catalog.py`). Strictly blocks all DDL (`CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `RENAME`) and DCL/TCL/Admin statements while injecting parenthesized `profile_id` + `scope` predicates across SQLite, PostgreSQL, MySQL/MariaDB, SQL Server, and DuckDB.

### 3.2 Zero-Mock Production Policy
- No production code in `backend/src/` or `frontend/src/` may employ fake, dummy, or facade mock implementations.
- All test doubles and fixtures must reside exclusively within `backend/tests/` or `frontend/tests/` (and reusable pack testing helpers in `frontend/src/testing/`).

---

## 4. Orchestration Nodes & LangGraph Lifecycle

`yarvelle-core` executes turns through a deterministic LangGraph workflow compiled identically in both `AgentExecutionService.execute_turn` and `AgentExecutionService.execute_resume_turn`:

```
[User Input]
     │
     ▼
┌────────────────────────────────────────────────────────┐
│ Phase 1: Context Load & Scoped Memory Recall           │ ◄── MemoryPort.recall(query, scope_context)
└────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: Input Guardrail & Safety Policy Validation    │ ──► [Safety / Boundary Violation] ──► [RefusalNode]
└────────────────────────────────────────────────────────┘
     │ (Passed)
     ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: Orchestrate & Provision                       │ ◄── SINGLE | PARALLEL | PIPELINE | DELIBERATE
└────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────┐
│ Phase 4: Execution Dispatcher / Deliberation Subgraph  │ ◄── Propose -> CrossExamine -> SelectiveRevise
└────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────┐
│ Phase 5: Synthesize, Union Guardrail & Staged Gate     │ ──► [Interrupt for Staged Action Approval / SSE Stream]
└────────────────────────────────────────────────────────┘
```

---

## 5. Rules of Engagement for AI Coding Agents

All AI coding assistants operating within `yarvelle-core` must adhere to the following rules:

1. **Minimal Change Principle**:
   - Modify only files directly relevant to the assigned task. Never perform unsolicited refactoring or stylistic reformatting.
2. **Strict Domain Neutrality**:
   - Never introduce domain-specific terminology (health, clinical, therapy, finance, tax, etc.) into `backend/src/`, `backend/tests/`, `frontend/src/`, or `frontend/tests/`.
   - Always verify with `PYTHONPATH=backend/src uv run --project backend pytest backend/tests/test_neutral_words_scan.py`.
3. **License Header Integrity**:
   - Every `.py`, `.ts`, `.tsx`, `.js`, `.mjs`, and `.css` file must begin with the official Spectrayan PolyForm Noncommercial + Yarvelle Core Additional Terms copyright header.
   - Verify compliance using `python3 scripts/check_licenses.py`.
4. **Design Token & RTL Purity (`@yarvelle/ui`)**:
   - Frontend components in `frontend/src/` must use semantic `@yarvelle/ui` design tokens and W3C CSS logical properties (`ms-`, `me-`, `ps-`, `pe-`, `text-start`, `text-end`). Raw hex/RGB colors, Tailwind palette utilities, `dark:` modifiers, and physical directional classes (`ml-`, `mr-`, `pl-`, `pr-`, `left-`, `right-`) are blocked by `frontend/tests/token-lint.test.ts`.
5. **Safety & Security Invariants**:
   - Never weaken `ScopeContext` isolation, `is_same_domain` validation, `declared_reads` + grant checks, `TaintFlag` propagation, path traversal protections, or forced human approval on panel-staged actions.
   - Ensure `AgentExecutionService.execute_turn` and `AgentExecutionService.execute_resume_turn` always compile identical graph topologies.
6. **Verification Gates**:
   - Before completing any task, execute the full verification matrix:
     ```bash
     # 1. License Header & Git-Dependency Checks
     python3 scripts/check_licenses.py
     python3 scripts/check_no_git_deps.py

     # 2. Backend Import Boundary Linter
     cd backend && PYTHONPATH=src uv run lint-imports && cd ..

     # 3. Domain-Neutral Vocabulary Scan
     PYTHONPATH=backend/src uv run --project backend pytest backend/tests/test_neutral_words_scan.py

     # 4. Full Backend Unit, Integration, Conformance & Eval Suite
     PYTHONPATH=backend/src uv run --project backend pytest backend/tests/

     # 5. Frontend Typecheck, Token Lint & Vitest Suite
     pnpm --dir frontend run typecheck
     pnpm --dir frontend test

     # 6. Frontend Production Package Build (@yarvelle/ui)
     pnpm --dir frontend run build
     ```
7. **Schema & Documentation Synchronization**:
   - Any modification to `PackSpec`, `AgentManifest`, or `SkillManifest` must regenerate canonical JSON schemas via `python3 scripts/generate_schemas.py` and keep `schemas/*.json` and `backend/src/yarvelle_core/schemas/*.json` synchronized.
   - Architectural changes to orchestration, scope isolation, or deliberation must be reflected in `docs/adr/`.
8. **Repository Content Policy (Framework & Test Code Only)**:
   - Commit only production framework code, tests, starter templates, canonical JSON schemas, user/contributor documentation, and required build/verification scripts.
   - Never commit AI-agent session or planning artifacts (scratch notes, research drafts, `.agents/` state, implementation plans), local runtime data (`logs/`, `*.db`), or unrequested lockfile churn.
