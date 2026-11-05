# Judge calibration labels

These YAML files are **human-style labels** for measuring LLM-judge agreement.
They are fixtures written by people, **not** model output and **not** cassette
recordings. Every case sets `kind: human_label`.

Do not paste live model replies here. Judge recordings (when committed) live
under `cassettes/` and must be genuine model output.

## Judge cassette recordings

Genuine Ollama judge exchanges for these cases (when committed) live under
`../cassettes/calibration/<case-id>/ollama-llama3.1-8b.jsonl`. Replay them with:

```bash
YARVELLE_EVAL=1 python -m yarvelle_core.testing.orch_eval calibrate \
  --backend replay --judge-model llama3.1:8b
```
