# Template Agent

Canonical template providing boilerplate manifest configuration, persona definitions, starter prompts, and golden evaluations for new Carefold agents.

## Overview

Use this folder as the starter foundation when authoring a new specialist agent for Carefold. Copy `agents/_template/` to `agents/<your-agent-id>/`, configure `agent.yaml`, update `starters.json`, and define golden evaluation test cases in `evals/golden.jsonl`.

## Key Capabilities

- **Declarative Architecture**: Demonstrates proper configuration of skills, sandboxed tools, and safety boundaries.
- **Marketplace Ready**: Includes required metadata for display on the Carefold web marketplace (`/`) and chat shell (`/chat`).
- **Eval Harness**: Provides baseline allow and refuse test cases for verification with `carefold eval`.

## Declared Skills & Tools

- **Skills**: `_template`
- **Effective Tools**: `[]` (Add Phase 0 tools: `attach-read`, `workspace-note`, `skill-docs` as needed)
- **Risk Class**: `wellness`

## Important Safety Information

All Carefold agents operate within closed non-clinical boundaries. Agents may not provide clinical diagnosis, dosing, emergency triage, or medication changes.

## Example Terminal Usage

```bash
carefold run --agent _template "Hello! What capabilities does this template agent have?"
```
