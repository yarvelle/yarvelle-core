# ADR-0014: Domain-Neutral Runtime Boundary, Handlebars Prompt Overrides, and Fail-Closed Connector Stubs

- **Status:** Accepted
- **Date:** 2026-11-11
- **Issue:** `#52`

## Context

`yarvelle-core` is the domain-neutral AI agent runtime powering multiple vertical products (such as Carefold for household health navigation and Yewly for education/learning workflows). Prior to this change:

1. Core runtime prompts in `middleware/skills.py`, `engine/orchestration/runtime.py`, `tools/db_query_planner.py`, `workflows/nodes/orchestrator_node.py`, `workflows/deliberation/*.py`, and `testing/orch_eval/judge.py` were embedded inline in Python strings (including 911/988 medical triage instructions), preventing pack-level template overrides.
2. `test_neutral_words_scan.py` exempted 41 runtime files via `ALLOWLIST` and omitted domain terms such as `phi`, `mrn`, `healthcare`, `dosing_units`, and `all_cessation_drugs`.
3. `engine/tool_registry.py` used unprefixed `from connectors.starters.calendar import GoogleCalendarConnector` imports and returned fabricated `"sent_via_approved_mcp"` / empty list payloads from `_exec_gmail_send_message` and `_exec_gmail_list_messages` when no MCP server was configured.

## Decision

1. **Handlebars Prompt Extraction & Pack Override Resolution:**
   - Extract all inline core prompts to `.hbs` files under `yarvelle_core/resources/prompts/templates/`.
   - Add `ResourceLoader.render_template(template_name, context, *, pack_id=None)` backed by `PackResourceResolver` (allowing `.hbs` / `.handlebars` under `prompts` prefixes) so domain packs override prompts declaratively without editing Python code.
2. **Domain-Neutral Sensitivity & Access Model:**
   - Replace medical/PHI identifiers across core schemas, ORM models, safety gates, chunkers, and tool governance with neutral equivalents (`data_sensitivity="restricted"`, `strip_sensitive`, `allow_assist`, `view_records`, `RiskClass.ASSIST`, `StructuralChunker`, `DEFAULT_RECORD_ID_TAG`).
   - Add idempotent Alembic migration `0014_neutralize_profile_columns` to rename legacy SQLite columns cleanly on upgrade.
   - Expand `test_neutral_words_scan.py` with `phi`, `mrn`, `healthcare`, `dosing_units`, and `all_cessation_drugs`, and remove all runtime Python files from `ALLOWLIST`.
3. **Prefixed Connector Imports & Fail-Closed Gmail MCP Delegation:**
   - Prefix all internal connector imports with `yarvelle_core.connectors` and remove the `sys.modules["connectors"]` alias hack.
   - Route `gmail_list_messages` and `gmail_send_message` through an attached MCP client (`UntrustedResult` taint wrapper) or raise `ConnectorNotConfiguredError` when unconfigured.

## Consequences

- Non-healthcare packs inherit clean, domain-neutral prompts, schemas, and error slugs out of the box.
- Healthcare packs supply clinical triage disclosures, drug/dosing safety regex blocks, and `RiskClass.register("clinical_assist")` extensions inside their own pack resources.
- Built-in connector tools never report fabricated email deliveries when no MCP transport is attached.
