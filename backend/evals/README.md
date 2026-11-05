# Orchestration evals (local only)

Multi-agent, multi-turn conversations used to evaluate the orchestration
runtime against a scripted fake model, a local Ollama model or a metered
provider.
The default Ollama subject is `glm-4.7-flash:latest`; pass
`--model qwen3:8b` (or another installed tag) to select a different subject.
The judge stays on a separate family (`llama3.1:8b` by default). These evals never run on CI.

Layout:

- `orchestration/scenarios/*.yaml`: one conversation per file. The format is
  defined in `yarvelle_core.testing.orch_eval.schema`; unknown keys fail.
- `orchestration/pack/`: the default neutral eval pack the scenarios run
  against (`pack.yaml` with the routing config, and `agents/<id>/` in the
  normal agent layout). It has everyday-task agents only, one hidden agent
  and two fixed routes. Tools listed under `offline_tools` are local no-op
  stand-ins. `guardrail_flags` lists the words that raise each guardrail
  flag; the harness input guardrail raises a flag when the user's text
  contains one of them, so a flag route fires from the text alone.
- `orchestration/packs/<pack-id>/`: extra eval packs (for example a
  forty-agent registry used by scale scenarios). Scenarios name a pack by
  id; the runner finds `pack/` or `packs/<id>/` next to them.
- `conftest.py`: the pytest gate described below.

This directory is not part of the wheel or the sdist, and it sits outside the
pytest `testpaths`, so `pytest backend/tests/` never collects it.

## Running

```bash
# Validate scenario files, including agent ids and routes against the pack
YARVELLE_EVAL=1 uv run --project backend yarvelle-core eval orchestration lint backend/evals/orchestration/scenarios

# Run them on the scripted fake backend (free, offline). Prints a JSON
# result; exits 1 when any check fails.
YARVELLE_EVAL=1 uv run --project backend yarvelle-core eval orchestration run backend/evals/orchestration/scenarios

# Through pytest
just eval-orch
```

The pack is found next to the scenarios by its id; pass `--pack DIR` to use
another one. `run --scenario ID` runs a single scenario and `--out FILE`
also writes the JSON result to a file.

## What a run checks

Each scenario runs through the real graph on one thread, one turn at a time.
The driver sends only what a caller sends (the message, an explicit agent
pick and attachments); the graph resets routing state between turns, raises
guardrail flags and writes the route audit records itself. For every turn the
driver collects the route decision, the raised flags, the route and hand-off
audit records, the stored hand-off records, the `task_status` and
`orchestration_notice` stream events, provenance and the final reply, then
checks:

- always: the turn finished, a reply exists, no more hand-offs than the
  call cap, hidden agents never ran, provenance carries the agent titles,
  no subagent tokens reached the stream, the reply names no agent ids, the
  route has a matching `route.*` audit record, every hand-off has one stored
  record with the same final state, a pick of a hidden agent was refused
  (with a `route.rejected` record) and the turn routed instead, and (on the
  fake backend) the script matched the calls made;
- when the scenario sets them: the route, required and forbidden agents,
  the guardrail flag raised from the text (`input.guardrail_flag`), the
  route, required and forbidden agents, task-call bounds, continuity with an
  earlier turn, task states, notices, provenance citations and missing parts,
  reply text and budgets.

The fake backend replays the `fake:` script of each turn: main-agent steps
(`task`, `answer`, `error` or `route`) and per-agent replies (text,
`{error: ...}` or `{tool: name}`).

Faults, restarts and cancel:

- top-level `faults:` injects timeout, error, truncate, slow, empty, garbage,
  inject or audit_error on a turn (and `cancel_after_ms` for a user cancel);
- `restart_before: true` on a turn rebuilds the graph on the same checkpointer
  so the thread resumes mid-conversation;
- `encrypt_checkpoints: true` seals every checkpoint blob for that scenario;
- `expect.cancelled` and `expect.error_matches` cover cancel and hard failures.


A scenario's `routing` picks the graph it runs on:

- `hybrid` (the default): the pack's fixed routes, then the main agent, then
  the default agent;
- `classifier`: the pack's fixed routes, then a routing model that picks one
  agent (script it with a `route: <agent-id>` step); the route is
  `model_classified`;
- `builtin`: no pack routes. Attachments take core's built-in document route
  (`fixed_route:builtin-documents`); other turns go to the routing model.

## Gates

1. Not collected by default: scenarios live outside `backend/tests`.
2. Opt-in: pytest items need the `orch_eval` marker, `-m orch_eval` and
   `YARVELLE_EVAL=1`; the CLI needs `YARVELLE_EVAL=1`.
3. CI refusal: if any CI environment variable is set (`CI`,
   `GITHUB_ACTIONS`, `RUNNER_NAME` and others), every entry point exits with
   code 3 before doing anything else, even when opted in. There is no
   override.
4. Workflow guard: `backend/tests/test_orch_eval_ci_guard.py` runs in the
   normal suite and fails if a workflow references these evals, a local model
   runtime or a provider key, or if the CI refusal stops working.

Reports are written under `~/.yarvelle-evals/<run>/`, outside the repository.
