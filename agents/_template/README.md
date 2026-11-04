# Template Agent

Canonical template providing boilerplate manifest configuration, persona definitions, starter prompts, and golden evaluations for new agents.

## Overview

Use this folder as the starter foundation when authoring a new specialist agent. Copy `agents/_template/` to `agents/<your-agent-id>/`, configure `agent.yaml`, update `starters.json`, and define golden evaluation test cases in `evals/golden.jsonl`. Domain packs ship their own agents the same way.

## Key Capabilities

- **Declarative Architecture**: Demonstrates proper configuration of skills, sandboxed tools, and safety boundaries.
- **Catalog Ready**: Includes the metadata used to list the agent in the agent catalog and chat shell. Pack-specific catalog fields go under `extensions` in `metadata.yaml`.
- **Eval Harness**: Provides baseline allow and refuse test cases for verification.

## Declared Skills & Tools

- **Skills**: `_template`
- **Effective Tools**: `[]` (Add Phase 0 tools: `attach-read`, `workspace-note`, `skill-docs` as needed)
- **Risk Class**: `education`

## Important Safety Information

All agents run inside the core safety policy and the forbidden intents declared in their manifest. Packs may add stricter rules of their own.
