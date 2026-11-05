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

"""Local Ollama backend for the orchestration eval harness.

Free and offline once the pinned models are pulled. Importing this module
never opens a socket; availability is probed on demand.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from yarvelle_core.testing.orch_eval.backends import FREE, CostTable, Role
from yarvelle_core.testing.orch_eval.defaults import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_JUDGE_MODEL,
    DEFAULT_OLLAMA_SUBJECT_MODEL,
    DEFAULT_SEED,
    DEFAULT_TEMPERATURE,
)


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama daemon or a required model is not available."""


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    base_url: str
    models: List[str] = field(default_factory=list)
    digests: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def has(self, name: str) -> bool:
        if name in self.models:
            return True
        # Accept "glm-4.7-flash" when tags list "glm-4.7-flash:latest", and the
        # reverse; also keep the prior prefix match for quantized variants.
        aliases = {name}
        if name.endswith(":latest"):
            aliases.add(name[: -len(":latest")])
        else:
            aliases.add(f"{name}:latest")
        for m in self.models:
            if m in aliases or m == name or m.startswith(name + "-"):
                return True
            if m.endswith(":latest") and m[: -len(":latest")] in aliases:
                return True
        return False


def probe_ollama(base_url: str = DEFAULT_OLLAMA_BASE_URL, timeout_s: float = 2.0) -> OllamaStatus:
    """Asks the local daemon for its tags. Never raises; reports in the status."""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as err:
        return OllamaStatus(reachable=False, base_url=base_url, error=f"{type(err).__name__}: {err}")
    models: List[str] = []
    digests: Dict[str, str] = {}
    for entry in payload.get("models") or []:
        name = str(entry.get("name") or "")
        if not name:
            continue
        models.append(name)
        digest = entry.get("digest") or entry.get("details", {}).get("parent_model") or ""
        if digest:
            digests[name] = str(digest)
    return OllamaStatus(reachable=True, base_url=base_url, models=models, digests=digests)


def require_ollama_models(
    required: Sequence[str],
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    status: Optional[OllamaStatus] = None,
) -> OllamaStatus:
    """Returns a live status, or raises with a clear skip/refusal message."""
    status = status or probe_ollama(base_url)
    if not status.reachable:
        raise OllamaUnavailableError(
            f"Ollama is not reachable at {base_url}: {status.error or 'unknown error'}. "
            f"Install and start Ollama, or run with --backend fake."
        )
    missing = [m for m in required if not status.has(m)]
    if missing:
        raise OllamaUnavailableError(
            f"Ollama is up but missing model(s): {', '.join(missing)}. "
            f"Pull with: " + "; ".join(f"ollama pull {m}" for m in missing)
        )
    return status


class OllamaBackend:
    """Eval backend that builds chat models through the core model factory.

    Subject and judge models are built with ``reasoning=False`` by default so
    thinking models (for example Qwen3) return their reply in ``content``
    instead of an empty body with unused thinking tokens. Pass
    ``reasoning=True`` (or ``None`` for the model default) when a run needs
    the thinking channel. The flag is forwarded to ChatOllama as ``think``.
    """

    name = "ollama"
    cost_per_mtok: CostTable = FREE

    def __init__(
        self,
        *,
        subject_model: str = DEFAULT_OLLAMA_SUBJECT_MODEL,
        judge_model: str = DEFAULT_OLLAMA_JUDGE_MODEL,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        seed: int = DEFAULT_SEED,
        temperature: float = DEFAULT_TEMPERATURE,
        reasoning: Optional[bool] = False,
        require_ready: bool = True,
        status: Optional[OllamaStatus] = None,
    ) -> None:
        self.subject_model = subject_model
        self.judge_model = judge_model
        self.base_url = base_url.rstrip("/")
        self.seed = seed
        self.temperature = temperature
        self.reasoning = reasoning
        self._status = status
        self._models: Dict[str, Any] = {}
        if require_ready:
            self._status = require_ollama_models(
                (subject_model, judge_model), base_url=self.base_url, status=status
            )

    def _ensure_status(self) -> OllamaStatus:
        if self._status is None:
            self._status = probe_ollama(self.base_url)
        return self._status

    def model_for(self, role: Role) -> Any:
        key = "judge" if role.kind == "judge" else "subject"
        if key in self._models:
            return self._models[key]
        from yarvelle_core.model.factory import create_chat_model

        name = self.judge_model if key == "judge" else self.subject_model
        model_kwargs: Dict[str, Any] = {
            "provider": "ollama",
            "model": name,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "streaming": True,
            "seed": self.seed,
        }
        if self.reasoning is not None:
            model_kwargs["reasoning"] = self.reasoning
        model = create_chat_model(**model_kwargs)
        self._models[key] = model
        return model

    def describe(self) -> dict[str, Any]:
        status = self._ensure_status()
        return {
            "backend": "ollama",
            "base_url": self.base_url,
            "subject_model": self.subject_model,
            "judge_model": self.judge_model,
            "subject_digest": status.digests.get(self.subject_model),
            "judge_digest": status.digests.get(self.judge_model),
            "temperature": self.temperature,
            "seed": self.seed,
            "reasoning": self.reasoning,
            "reachable": status.reachable,
        }


__all__ = [
    "OllamaBackend",
    "OllamaStatus",
    "OllamaUnavailableError",
    "probe_ollama",
    "require_ollama_models",
]
