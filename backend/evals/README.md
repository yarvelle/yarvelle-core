# Orchestration evals (local only)

Multi-agent, multi-turn conversations used to evaluate the orchestration
runtime against a scripted fake model, a local Ollama model or a metered
provider. These evals never run on CI.

Layout:

- `orchestration/scenarios/*.yaml`: one conversation per file. The format is
  defined in `yarvelle_core.testing.orch_eval.schema`; unknown keys fail.
- `conftest.py`: the pytest gate described below.

This directory is not part of the wheel or the sdist, and it sits outside the
pytest `testpaths`, so `pytest backend/tests/` never collects it.

## Running

```bash
# Validate scenario files
YARVELLE_EVAL=1 uv run --project backend yarvelle-core eval orchestration lint backend/evals/orchestration/scenarios

# Through pytest
just eval-orch
```

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
