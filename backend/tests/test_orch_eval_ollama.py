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

"""Unit tests for the Ollama eval backend (no live model calls)."""

from __future__ import annotations

import pytest

from yarvelle_core.testing.orch_eval.defaults import (
    DEFAULT_OLLAMA_JUDGE_MODEL,
    DEFAULT_OLLAMA_SUBJECT_MODEL,
)
from yarvelle_core.testing.orch_eval.ollama_backend import (
    OllamaBackend,
    OllamaStatus,
    OllamaUnavailableError,
    require_ollama_models,
)


def test_pinned_default_tags():
    assert DEFAULT_OLLAMA_SUBJECT_MODEL == "glm-4.7-flash:latest"
    assert DEFAULT_OLLAMA_JUDGE_MODEL == "llama3.1:8b"


def test_require_ollama_models_unreachable():
    status = OllamaStatus(reachable=False, base_url="http://127.0.0.1:9", error="down")
    with pytest.raises(OllamaUnavailableError, match="not reachable"):
        require_ollama_models(["qwen3:8b"], status=status)


def test_require_ollama_models_missing():
    status = OllamaStatus(reachable=True, base_url="http://127.0.0.1:11434", models=["llama3.2:latest"])
    with pytest.raises(OllamaUnavailableError, match="missing model"):
        require_ollama_models(["qwen3:8b", "llama3.1:8b"], status=status)


def test_ollama_backend_describe_without_network():
    status = OllamaStatus(
        reachable=True,
        base_url="http://127.0.0.1:11434",
        models=["glm-4.7-flash:latest", "qwen3:8b", "llama3.1:8b"],
        digests={
            "glm-4.7-flash:latest": "abc",
            "qwen3:8b": "qwen-dig",
            "llama3.1:8b": "def",
        },
    )
    backend = OllamaBackend(require_ready=True, status=status)
    described = backend.describe()
    assert described["backend"] == "ollama"
    assert described["subject_model"] == "glm-4.7-flash:latest"
    assert described["judge_model"] == "llama3.1:8b"
    assert described["subject_digest"] == "abc"
    assert described["reasoning"] is False
    assert backend.cost_per_mtok.is_free


def test_status_has_matches_latest_alias():
    status = OllamaStatus(
        reachable=True,
        base_url="http://127.0.0.1:11434",
        models=["glm-4.7-flash:latest", "qwen3:8b"],
    )
    assert status.has("glm-4.7-flash:latest")
    assert status.has("glm-4.7-flash")
    assert status.has("qwen3:8b")
    assert not status.has("missing-model")
