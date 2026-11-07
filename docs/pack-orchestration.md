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
    reminder:               # optional, off by default; model input only
      when: follow_up       # follow_up (default) or always
      text: |
        (Follow-up: apply the hand-off rules to this new message.)
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

## Per-turn delegation reminder

With some models (seen with local models such as `glm-4.7-flash`), rules that
appear only in the system prompt stop working once the conversation has
history. On a follow-up turn the model answers from its earlier reply instead
of handing the new question to a specialist. `delegation.reminder` puts a short
reminder next to the latest user message:

- The reminder is added to the main agent's **copy** of the turn's latest user
  message, after a blank line. For multipart content it is added as an extra
  text block. It is not a separate system message, because some providers
  accept system text only at the start.
- It is **model input only**. The checkpoint, conversation history, stream and
  audit keep the user's own words. Only the main agent sees it; specialists get
  their task brief as before.
- `when: follow_up` (the default) adds it only when the conversation already
  has a reply. `when: always` adds it on every turn that ends with a user
  message.
- `text` is required, must not be blank, and can be up to 2000 characters.
  Unknown keys are rejected when the pack loads.
- When `reminder` is not set, nothing changes and the main agent reads the
  messages as before.

### Python hook

A pack that needs its own logic can pass a hook instead of, or on top of, the
`pack.yaml` text. A hook replaces the `pack.yaml` reminder.

```python
from yarvelle_core.engine.orchestration.reminder import is_follow_up

def reminder(messages, state):
    # messages: the turn's messages, ending with the user's; state: graph state.
    # Return the reminder text, or None for no reminder this turn.
    return "(Follow-up: hand this to the right specialist again.)" if is_follow_up(messages) else None

GraphBuilder(..., main_agent_reminder=reminder)          # or .with_main_agent_reminder(reminder)
AgentExecutionService(..., main_agent_reminder=reminder)  # built-in routing graph
```

For evals, the orch_eval driver applies the `pack.yaml` reminder automatically.
An `EvalPack` subclass can return the same hook from `main_agent_reminder()`.
