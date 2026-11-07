# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.4] - 2026-11-07

This patch release adds configurable safety guards that run after a pack's safety policy, an opt-in buffered answer release, and a final output check on resumed turns. With no guards configured, normal turns behave as in 0.2.3. `pack_api` stays 1: `safety` is a new optional block in `pack.yaml`.

### Added
- **Safety guards** (#46, #48). Packs can declare `safety.guards` in `pack.yaml`: regex `rules` checks (named fragments, normalization, exempt spans, sentence-scoped patterns, `rules_file`) and `model` checks that call any LangChain chat model through the existing model factory (Ollama, OpenAI, Anthropic, Google, custom). Presets `llama_guard`, `granite_guardian`, `labels` and `json` read the reply. Checks run in `enforce`, `shadow` or `off` mode. The pack's policy decides first, a rules block can't be undone by a model, and timeouts, failed calls, unreadable replies and abstentions refuse by default. Every evaluation is audited without the checked text (`add_guard_audit_hook`). Models and modes can be set with `<PREFIX>_SAFETY_GUARD_<ID>_*` env vars, and `<PREFIX>_SAFETY_GUARDS` adds env-only checks, which run in shadow by default. Core ships no guard model. See `docs/safety-guards.md`.
- **Buffered answer release** (#47 via #48). `safety.guards.release: buffered`, `AgentExecutionService(output_release="buffered")` or `<PREFIX>_SAFETY_OUTPUT_RELEASE=buffered` holds answer tokens until the final check passes, then sends the answer as one token event; a refused answer is never sent. The default stays `stream`, where `done.refused` tells the client to replace the streamed text.
- **Unconfigured model checks are reported** (#48). A model check with no model and `when_unconfigured: allow` (the default) logs `safety_guard_model_not_configured` once at startup, naming the check. `when_unconfigured`, `on_abstain` and `on_error` accept `refuse`.

### Changed
- **Resumed turns get the final output check** (#48). `execute_resume_turn` now runs the same final output check as a normal turn, for every policy. A hard refusal replaces the resumed answer with the refusal template.
- **Async safety checks** (#46). The guardrail nodes and the service call the new `acheck_input` / `acheck_output` helpers. Existing synchronous policies are called exactly as before.

### Fixed
- **Llama Guard system messages** (#48). Llama Guard's chat template has no system role, so `preset: llama_guard` with `system` is now rejected at load instead of being judged as a conversation turn.

## [0.2.3] - 2026-11-07

This patch release adds an optional per-turn delegation reminder for the main agent and fixes main-agent refusals and multi-turn evals. Nothing is removed or renamed, every new setting is off by default, and packs built for 0.2.2 work unchanged. `pack_api` stays 1.

### Added
- **Per-turn delegation reminder for the main agent** (#44). Packs can set `orchestration.delegation.reminder` (`text`, and `when: follow_up` or `always`) to add a short reminder to the main agent's copy of the latest user message. This helps models that ignore system-prompt delegation rules on follow-up turns. It is model input only: the checkpoint, history, stream and audit keep the user's words. Packs can also pass a Python hook with `main_agent_reminder` on `GraphBuilder` or `AgentExecutionService` (`reminder` on `HybridRouter`). The orch_eval driver applies it too, and an `EvalPack` can return the hook from `main_agent_reminder()`. See `docs/pack-orchestration.md`.
- **Pack graph nodes under eval** (#41). `EvalPack.graph_nodes()` lets an eval pack supply the nodes it replaces in production (for example its refusal node). Names are checked against the new `engine.builder.OVERRIDABLE_NODES`.

### Fixed
- **Refused main-agent answers** (#43, fixes #39). When the output guardrail refused a main-agent answer, the reflection retry ran it on the single-agent node and failed with "Unknown or unregistered agent ID: 'main-agent'". The turn now ends on the refusal path. This holds even when a pack's own reflection node asks for a retry. Specialist answers are still retried.
- **Per-turn state in multi-turn evals** (#40, fixes #30). The orch_eval driver now resets per-turn state the way the chat service does, through a shared `turn_reset_values()` helper. A routine turn after a refusal no longer re-reads the old refusal.
- **Hidden agents reached by a fixed route** (#42, fixes #32). The `hidden_agents_not_run` eval check now allows the hidden agent picked by the turn's pack fixed route. It still fails any other hidden-agent run.

## [0.2.2] - 2026-11-07

This patch release fixes dossier-type matching when packs register their own document types. Nothing is removed or renamed, and core-only setups behave as in 0.2.1.

### Fixed
- **Generic dossier type matched last** (#36). `get_routing_patterns()` now orders `dossier_types` as core-specific types, then pack types in registration order, then the catch-all `generic` type as the fallback. Before this, `generic` came first, so broad words such as "summary" or "document" shadowed more specific types registered through `routing_hints.patterns_resource`. Packs still cannot override core types.

## [0.2.1] - 2026-11-06

This release adds optional pack settings and opt-in features on top of 0.2.0. Nothing is removed or renamed, and every new setting defaults to the 0.2.0 behaviour, so packs built for 0.2.0 work unchanged.

### Added
- **Delegation instructions for the main agent** (#34). Packs can set `orchestration.delegation.instructions` to say when the main agent should hand work to specialists, for example on follow-up questions. The text is added after the base prompt under "When to hand work to specialists:" and before the synthesis instructions. It is empty by default. See `docs/pack-orchestration.md`.
- **Pack-native resources** (#28). A secure resolver lets packs ship routing and pattern resources inside the pack package.
- **Encryption at rest for audit bodies and long-term memory** (#29). Opt-in and off by default.
- **Local orchestration eval harness** (#20 to #26), local only and never run in CI:
  - fault injection, restart and cancel
  - Ollama and metered backends, with a spend cap that defaults to $0
  - JSON, Markdown and HTML reports with baseline compare
  - record and replay cassettes
  - an LLM judge with rubrics and calibration
  - paraphrase, adversarial and forty-agent scenarios
  - `glm-4.7-flash` as the default Ollama subject

### Fixed
- **Release metadata** (#27). A `version.py` module is the single version source, and the release config targets plain `vX.Y.Z` tags.
- **Route kept on cancel** (#21). A cancel during a hand-off keeps the route and agent decision.

## [0.2.0] - 2026-11-04

This release replaces keyword dispatch with subagent orchestration and makes routing and hand-offs auditable. It also adds opt-in encryption for checkpoints and a local-only harness for orchestration evals. It contains breaking changes; read **Upgrading from 0.1.x** below before updating.

### Breaking changes
- **Old dispatcher removed** (#12). `workflows/dispatcher.py` (`ExecutionDispatcher`), its builder node, and `with_dispatcher()` are gone. The builder option `include_dispatcher` is now `include_deliberation` (`GraphBuilder(include_deliberation=...)` / `with_deliberation()`). A `deliberate` plan runs in `DeliberationNode`. There is no fallback path or placeholder reply.
- **Strict audit writes** (#16). `record_audit` no longer swallows failures. If a strict event (`route.*`, `task.*`) can't be written to the database or the audit log, it raises `AuditWriteError` and the turn stops. Best-effort events are logged and counted (`best_effort_failure_count()`). A `mode=` argument overrides the default for one call.
- **Default agent comes from the pack** (#9). The domain default agent constants are removed. `AgentExecutionService(default_agent_id=...)`, `GraphBuilder(default_agent=...)` / `with_default_agent()` and `OrchestratorNode(default_agent=...)` take the default from the pack's `orchestration.default_agent`. A turn with no agent id and no default fails with a clear error instead of loading a stand-in agent. The unused specialist supervisor subgraph and the `SupervisorNode` alias are removed (#9, #11).
- **Agent metadata moves to `extensions`** (#9). `AgentManifest`, `AgentSummary` and `AgentDetailResponse` carry pack metadata in an `extensions` dict, and the legacy per-agent stages column is folded into it by migration `0012`.
- **Runtime identity from settings** (#10). Core carries no product name. Identity values (env prefix, home dir, DB filename, session cookie, URL scheme, OAuth client prefix, keychain service and entry, local key label and domain, vault salt, pack packages) are read through `yarvelle_core.identity` with neutral defaults (`YARVELLE_ENV_PREFIX`, `<PREFIX>_APP_SLUG` and per-value overrides). The default vault salt and keychain service are now neutral. The fallback that accepted a second session cookie name is gone. `@yarvelle/ui` codegen takes pack UI modules from `--pack-module <id>=<module>` and no longer defaults to a pack.
- **No silent routing fallbacks** (#11). Routing from `routing_patterns.yaml` prompt patterns, prompt-keyword deliberation and parallel plans, and silent substitution of an unknown agent are removed. An unknown agent goes to the default agent with a notice, or the turn fails with an error.
- **Hidden agents can't be picked directly** (#17). A direct API or service pick of a system agent or a `hidden` agent returns an error and records `route.rejected`. Picking the orchestrator is still allowed and means "route this turn".
- **Routing state is per turn** (#16). The previous turn's route decision, notices, provenance and guardrail flags are cleared when a turn starts. The one-turn agent pick and execution plan are dropped when it ends. The input guardrail now computes `guardrail_flags` from the user's text and replaces flags supplied by the caller. The service leaves `current_agent` / `explicit_agent` unset when no agent is named.
- **Response synthesizer heuristics removed** (#13). `strip_disclaimers`, `strip_reference_preamble` and `CONSTITUENT_DISCLAIMER_PATTERNS` are gone. Agents are named by registry title, not by a prettified id.

### Added
- **Subagent orchestration through the `task` tool** (#7, #8, #11). Multi-agent turns run as Deep Agents subagents handed work by a main agent.
  - Typed contracts: `PackOrchestrationSpec` (default agent, fixed routes, limits), `OrchestrationLimits`, `RouteDecision`, `task_status` and `orchestration_notice` stream events, and new audit event types and hand-off fields on `AuditEvent`.
  - An agent registry that reads file and stored agents into one catalog, with strict id lookup (`AgentNotFoundError`) and generated subagent specs that always carry tool-policy and audit middleware.
- **Hybrid routing with a guarded main agent** (#11). Turns are routed in a fixed order: the user-selected agent, then pack fixed routes (guardrail flags, attachments), then the default agent when no model is configured, then the main agent.
  - The main agent gets only the `task` tool and only visible registry agents.
  - `TaskGuardMiddleware` refuses unknown or hidden agents and enforces the per-turn hand-off cap and the per-agent and per-turn time limits. It audits `task.started` / `task.completed` / `task.failed` / `task.timed_out`.
  - If the main agent fails, the turn falls back to the default agent with a `main_agent_failed` notice.
- **Hardened hand-offs** (#12).
  - A failed or timed-out subagent no longer fails the turn. It produces a `partial_failure` notice.
  - A per-subagent call cap marks hand-offs that hit it as truncated.
  - A user cancel cancels every in-flight hand-off (`task.cancelled`).
  - Subagent tokens are kept out of the user stream.
- **Replies with provenance** (#13). New optional `orchestration.synthesis.instructions`. `TurnOutcome.provenance` records one entry per hand-off (agent, title, state, truncation, output hash, verified). The reply names any agent that did not answer.
- **Stored hand-offs** (#16). A new `turn_tasks` table keeps one row per hand-off (agent, state, truncation, verification, input and output hashes, error code, timing; no answer text). `audit_events` gains `turn_id`, `task_id`, `parent_task_id`, `input_hash`, `output_hash` and `error_code` (migration `0013`).
- **Every route is audited** (#16, #17): `route.user_selected`, `route.fixed`, `route.default`, `route.main_agent`, `route.classified` (model-classified turns) and `route.rejected`. The built-in document route is recorded as a fixed route.
- **Guardrail flags from the input** (#16). The safety policy can raise flags from the user's text (`check_flags` / `policy_flags()`), so flag-based fixed routes fire without the caller injecting them.
- **Opt-in routing in the service graph** (#17). `AgentExecutionService` and `execute_agent_run` accept an `orchestration` spec (and an optional `registry`). With a spec, the built-in graph routes unpinned turns through fixed routes, the main agent and the default agent. Without one, the graph is unchanged. `GraphBuilder` gains `include_main_agent`.
- **Checkpoint encryption at rest** (#18). Opt-in AES-256-GCM encryption of checkpoint blobs, under a key derived from the vault KEK with HKDF-SHA256.
  - Settings: `checkpoint_encryption`, `checkpoint_plaintext_reads` and `checkpoint_key_version`.
  - Key ids in each blob allow rotation.
  - A missing or wrong key fails loudly, with no plaintext fallback.
  - New CLI `yarvelle-core checkpoints status|encrypt|decrypt` with backup, dry run and a reverse path.
  - See `docs/checkpoint-encryption.md`.
- **Local-only orchestration eval harness** (#14, #15). `yarvelle_core.testing.orch_eval` adds:
  - a versioned scenario format and loader
  - a scripted fake backend and a multi-turn driver that runs scenarios through the real graph
  - deterministic checks, plus `yarvelle-core eval orchestration lint|run`
  - a neutral eval pack with scenarios under `backend/evals`

  Runs require `YARVELLE_EVAL=1` and refuse to start on CI.
- `list_agents` searches by query across id, title, description, category, tags and skills (#8).

### Changed
- Dependency floors raised: `langchain>=1.3.14` (now a direct dependency), `langgraph>=1.2.14`, `deepagents>=0.7.13` (#7).
- Templates, prompts, locale strings and the skill generator fallback text are domain-neutral. The skill generator writes `yarvelle.yaml`, and the `YAML_*` and skills prompt constants are renamed to neutral names (#9, #10).
- The relay callback check accepts the configured URL scheme (#10).
- Execution plans in state are dumped in JSON mode, which removes an `ExecutionMode` serialization warning (#16).

### Upgrading from 0.1.x
1. **Back up the database** before the first start on 0.2.0. Migrations run automatically on startup (`init_db`).
   - `0012_agent_extensions` moves the legacy agent stages column into `extensions` (its downgrade restores the column).
   - `0013_turn_tasks` adds the `turn_tasks` table and the new `audit_events` columns. It checks what exists before each step and can be rolled back.
2. **Keep your identity settings.** An install that relied on earlier product defaults must set `YARVELLE_ENV_PREFIX`, `<PREFIX>_APP_SLUG`, `<PREFIX>_DB_FILENAME`, `<PREFIX>_VAULT_SALT` and `<PREFIX>_PACK_PACKAGES` to its previous values. Otherwise the existing database, keychain entries and vault are not found. Pass `--pack-module` to the UI codegen.
3. **Packs:**
   - Set `orchestration.default_agent` in `pack.yaml`, or pass an agent id per turn.
   - Move agent stage metadata under `extensions`.
   - Replace imports of removed constants, the supervisor subgraph, `SupervisorNode`, the dispatcher and renamed symbols.
4. **Builder callers:** rename `include_dispatcher=` to `include_deliberation=` and `with_dispatcher()` to `with_deliberation()`.
5. **Audit callers:** handle `AuditWriteError` where strict events are recorded, and make sure the audit database and log path are writable.
6. **Direct agent picks:** callers that picked system or hidden agents directly must route through the orchestrator instead.
7. **Checkpoint encryption (optional, off by default).** Enable in this order:
   1. Make sure the vault key is available (OS keyring, `<PREFIX>_VAULT_KEK_FILE` or `<PREFIX>_VAULT_PASSPHRASE`).
   2. Set `checkpoint_encryption=true`.
   3. Stop the app and run `yarvelle-core checkpoints encrypt --dry-run`, then `yarvelle-core checkpoints encrypt`.
   4. Set `checkpoint_plaintext_reads=false`.
   5. Delete the backup written next to the database once the app has been checked.

   To revert: stop the app, run `yarvelle-core checkpoints decrypt`, then set `checkpoint_encryption=false`.
8. **Routing in the service graph is opt-in.** Turning it on for existing threads needs a check, because a thread checkpointed under the plain graph may not resume cleanly under the routed graph.

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
