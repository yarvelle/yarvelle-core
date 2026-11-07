# Safety guards

A pack's `SafetyPolicy` decides what a turn may say. **Safety guards** are extra
checks, configured in `pack.yaml` and environment variables, that run after the
policy:

- **`rules`** checks: regular expressions with named fragments, text
  normalization and exempt spans. Deterministic, fast, no model.
- **`model`** checks: a chat model you choose and run (a guard model such as
  Llama Guard or Granite Guardian, a classifier you trained and serve behind a
  chat endpoint, or a judge prompt). Core builds it with the same LangChain
  model factory as agent models, so Ollama, OpenAI-compatible servers and
  hosted providers all work and the model egress policy applies.

Core ships no guard model, never downloads one and holds no domain wording.
The pack supplies rules, prompts, labels and thresholds; the user supplies the
model.

## Guarantees

1. **The policy decides first.** If the pack's `SafetyPolicy` refuses, that
   verdict is final and no guard runs.
2. **Guards only add refusals.** A model saying "safe" can never undo a policy
   or rules refusal. When a rules check blocks, model checks are not called.
3. **Fail closed.** For model checks, by default a timeout, failed call,
   unreadable reply, "not sure" reply, or text longer than `max_chars` refuses
   the answer (`on_error: block`, `on_abstain: block`). Long text is never
   truncated to fit.
4. **No guard configured, no change.** Without `safety.guards` and without
   `<PREFIX>_SAFETY_GUARDS`, every policy is called exactly as before.
5. **Guard model output never reaches the user.** Guard calls run without
   streaming and are tagged `internal` / `no_stream`.

## Configuration

```yaml
# pack.yaml
safety:
  guards:
    deadline_s: 20            # budget for all model checks of one text
    refusal_template: "I can't share that answer. Please rephrase your question."
    checks:
      - id: account-secrets
        type: rules
        stages: [input, output]          # default for rules: both
        blocks:                          # <NAME> inserts a fragment
          VERB: [share, reveal, send]    # a list becomes (?:share|reveal|send)
          SECRET: "(?:the|your) (?:password|passcode|recovery code)"
        normalize:                       # applied first, in order
          - {pattern: "[*_`]", replace: ""}
        exempt:                          # blanked out before patterns run
          - "\\bnever <VERB> <SECRET>\\b"
        patterns:
          - {id: disclose-secret, category: credential_disclosure, pattern: "\\b<VERB> <SECRET>\\b"}
          - {id: urgent-transfer, pattern: "^transfer it now", scope: sentence}
        # rules_file: resources/safety/rules.yaml   # same keys, read from the pack

      - id: guard-model
        type: model
        preset: llama_guard              # how to talk to it and read its reply
        stages: [output]                 # default for model checks: output
        mode: shadow                     # enforce | shadow | off
        timeout_s: 8
        max_chars: 16000
        when_unconfigured: allow         # no model set: skip this check
        on_abstain: block
        on_error: block
        output:
          allow_labels: [safe]
          block_labels: [unsafe]
          block_categories: [S2, S7]     # only these categories count
```

The same example is in `docs/examples/safety-guards.pack.yaml`.

### Check fields

| Field | Applies to | Meaning |
|---|---|---|
| `id` | all | Slug. Names the check in audit records, refusal reasons and env vars. |
| `type` | all | `rules` or `model`. |
| `stages` | all | `input` (user message) and/or `output` (answer). |
| `mode` | all | `enforce` counts; `shadow` runs and is audited only; `off` does not run. |
| `required` | all | Env vars cannot switch a required enforce check to shadow or off. |
| `on_block` | all | `refuse` (replace the answer) or `warn` (keep it, flag a boundary warning). |
| `blocks`, `normalize`, `exempt`, `patterns`, `sentence_split`, `rules_file` | rules | See above. `rules_file` is read through the pack's contained resource resolver. |
| `max_chars` | all | Longer text is not checked and counts as abstained. |
| `preset` | model | `llama_guard`, `granite_guardian`, `labels`, `json`. |
| `style` | model | `moderation` (send the conversation as chat messages) or `prompt` (send one message from `prompt`). |
| `system` | model | Optional system message (for example the risk name for Granite Guardian). |
| `prompt`, `prompt_file` | model | Template for `style: prompt`. `{{text}}`, `{{prompt}}`, `{{stage}}` are replaced. |
| `output` | model | How to read the reply (below). |
| `model` | model | Optional defaults: `provider`, `model`, `base_url`, `temperature`. Env vars override. |
| `timeout_s` | model | Per call, default 10. |
| `include_prompt` | model | On the output stage, also send the user's message (default true). |
| `when_unconfigured` | model | `allow` skips the check when no model is set; `block` refuses. |
| `on_abstain`, `on_error` | model | `block` (default) or `allow`. |

### Reading the reply (`output`)

- `format: labels` (default): the first word of the reply is matched against
  `allow_labels`, `block_labels` and `abstain_labels`. Categories come from the
  rest of the line or the next line (`unsafe` / `S6`). Anything else is an
  error.
- `format: json`: the first JSON object is read; `decision` is matched against
  the same labels, `category` and `score` are optional. With
  `block_threshold` / `allow_threshold`, the score decides: at or above
  `block_threshold` blocks, at or below `allow_threshold` allows, in between
  abstains.
- `<think>...</think>` blocks are ignored. An unterminated one is an error.
- `block_categories`: when set, a block counts only if the model names one of
  them. Generic guard taxonomies rarely match a pack's policy one-to-one.

### Presets

| Preset | Style | Reply |
|---|---|---|
| `llama_guard` | moderation | `safe`, or `unsafe` with category codes on the next line |
| `granite_guardian` | moderation | `Yes` (risk found) or `No` |
| `labels` | prompt | first word is an allow or block label |
| `json` | prompt | JSON object with `decision` (and optionally `category`, `score`) |

A preset only describes the reply format. Validate any model on the pack's own
labelled examples in `shadow` mode before giving it `enforce`.

## Environment variables

`<PREFIX>` is `YARVELLE` unless `YARVELLE_ENV_PREFIX` sets another (see
`yarvelle_core.identity`). `<ID>` is the check id in upper case with `-`
written as `_`.

| Variable | Meaning |
|---|---|
| `<PREFIX>_SAFETY_GUARD_<ID>_PROVIDER` | `ollama`, `openai`, `anthropic`, `google`, `custom` |
| `<PREFIX>_SAFETY_GUARD_<ID>_MODEL` | model name at the provider |
| `<PREFIX>_SAFETY_GUARD_<ID>_BASE_URL` | endpoint for `ollama` / `custom` |
| `<PREFIX>_SAFETY_GUARD_<ID>_TIMEOUT_S` | per-call timeout, seconds |
| `<PREFIX>_SAFETY_GUARD_<ID>_MODE` | `enforce`, `shadow` or `off` (ignored for a required check) |

API keys use the provider's usual variables (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, ...) and are read by the model factory.

**Checks without pack YAML.** `<PREFIX>_SAFETY_GUARDS=lg` adds a check named
`lg`. It needs `<PREFIX>_SAFETY_GUARD_LG_PRESET` (`llama_guard` or
`granite_guardian`) plus `_PROVIDER` and `_MODEL`; `_STAGES`, `_SYSTEM` and
`_MODE` are optional. Env-only checks default to `shadow`. In `enforce` mode a
missing model refuses answers, because the user asked for the check by name.
An id the pack already declares configures that check instead.

Example, a local Llama Guard in shadow mode:

```bash
export YARVELLE_SAFETY_GUARDS=lg
export YARVELLE_SAFETY_GUARD_LG_PRESET=llama_guard
export YARVELLE_SAFETY_GUARD_LG_PROVIDER=ollama
export YARVELLE_SAFETY_GUARD_LG_MODEL=llama-guard3:1b
```

## Refusals

| Reason | When | Hard |
|---|---|---|
| `guard:<id>:<category>` | an enforced check blocked | yes |
| `guard_abstained:<id>` | a model was not sure, or the text was too long | yes |
| `guard_unavailable:<id>` | timeout, failed call, unreadable reply, missing required model | yes |
| `guard_unavailable:sync_call` | a synchronous `check_output` could not run model checks | yes |
| `guard_warn:<id>:<category>` | a check with `on_block: warn` blocked | no (boundary warning) |

Hard refusals show `refusal_template` (or the policy's refusal template) instead
of the answer. Precedence: policy refusal, then a guard block, then abstain or
error, then warn.

## Using guards from code

Packs loaded through the `yarvelle.packs` entry point get their `safety.guards`
applied automatically: the loader wraps the pack's `SafetyPolicy`, and a broken
guard configuration fails the pack load. An application that builds its policy
itself wraps it once:

```python
from yarvelle_core.engine.guards import build_guarded_policy

policy = build_guarded_policy(pack_spec.safety_policy, pack=pack_spec)
service = AgentExecutionService(safety_policy=policy, ...)
```

`build_guarded_policy` returns the policy unchanged when there are no checks.
It also accepts `chat_models={"check-id": model}` (a ready LangChain chat
model, used in tests with fakes), `extra_checks=[...]` (Python checks that
implement `GuardCheck`) and `audit_hooks=[...]`.

Graph nodes and the service call `acheck_input` / `acheck_output`
(`yarvelle_core.engine.safety_policy`). For policies without guards these call
`check_input(text)` / `check_output(text)` exactly as before.

## Audit hook

Each evaluation produces a `GuardAuditRecord`: stage, outcome, reason, per-check
decision, mode, category, latency, model label and the text length. It never
holds the checked text, the user's message or the model's reply. Records are
logged as `safety_guard_evaluated`; register more hooks with
`add_guard_audit_hook(fn)`. A failing hook is logged and does not change the
verdict.

## Streaming

Guards check the complete answer. In the default stream mode, answer tokens
reach the client while the answer is generated and the `done` event carries
the final verdict: when `done.refused` is true, the client must replace the
streamed text with `done.fullText`. Text-to-speech, notifications and saved
previews should wait for `done`.
