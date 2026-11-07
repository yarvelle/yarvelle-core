# Pack orchestration settings

A pack configures multi-agent turns with the `orchestration:` block in `pack.yaml`
(`PackOrchestrationSpec`, see `schemas/pack.schema.json`). Every key except
`default_agent` is optional.

```yaml
orchestration:
  schema_version: 1
  default_agent: budget-planner
  fixed_routes: []          # deterministic routes, checked before any model call
  limits:                   # fan-out and timeout bounds for one turn
    max_agents: 3
  delegation:
    instructions: |
      Hand follow-up questions about an earlier specialist answer back to that
      specialist, even when the question looks simple.
  synthesis:
    instructions: |
      Keep the reply short and list any missing part first.
```

## Main agent prompt

The main agent's system prompt is the core base prompt followed by the pack's
sections, in this order. Empty or whitespace-only instructions are left out, so
a pack that sets neither gets the base prompt unchanged.

1. The base prompt. It tells the main agent to answer directly when no
   specialist is needed and otherwise hand work to the listed agents with the
   `task` tool.
2. `delegation.instructions`, under the heading
   `When to hand work to specialists:`. Use it to say when the pack's
   specialists should take a request that the main agent might otherwise answer
   itself, for example follow-up questions, requests that need a tool only a
   specialist has, or topics the main agent should never answer alone.
3. `synthesis.instructions`, under the heading `How to compose the reply:`.
   Use it for the shape and tone of the final reply.

Each instructions field is plain text of up to 4000 characters. Unknown keys
inside `delegation` or `synthesis` are rejected when the pack loads.

Delegation instructions guide the model; they do not force a route. For a
request that must always reach one agent, use a fixed route instead.
