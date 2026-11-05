# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Pinned defaults for local and paid orchestration eval backends."""

from __future__ import annotations

# Subject model under test (tool-calling, 8B class). Exact Ollama tag.
DEFAULT_OLLAMA_SUBJECT_MODEL = "qwen3:8b"

# Separate-family judge model (8B class). Exact Ollama tag.
DEFAULT_OLLAMA_JUDGE_MODEL = "llama3.1:8b"

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_SEED = 1729
DEFAULT_TEMPERATURE = 0.0

# Paid provider defaults (only used when --max-usd > 0 and a key is supplied
# at run time; importing this module never loads a key).
DEFAULT_PROVIDER = "openai"
DEFAULT_PROVIDER_SUBJECT_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER_JUDGE_MODEL = "gpt-4o-mini"

__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_OLLAMA_JUDGE_MODEL",
    "DEFAULT_OLLAMA_SUBJECT_MODEL",
    "DEFAULT_PROVIDER",
    "DEFAULT_PROVIDER_JUDGE_MODEL",
    "DEFAULT_PROVIDER_SUBJECT_MODEL",
    "DEFAULT_SEED",
    "DEFAULT_TEMPERATURE",
]
