# Orchestration eval cassettes

Committed, domain-neutral recordings for the local orch-eval harness.

- Layout: `<pack>/<scenario>/<backend>-<model>.jsonl`
- Replay: `YARVELLE_EVAL=1 yarvelle-core eval orchestration run --backend replay …`
- Record: add `--record` to a live `ollama` or `provider` run
- App-specific recordings belong outside this tree (or under a gitignored
  `cassettes.local/` directory). Override the root with `--cassette` or
  `YARVELLE_CASSETTES_DIR`.
