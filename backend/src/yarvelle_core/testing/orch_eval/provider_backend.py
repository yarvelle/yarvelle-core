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

"""Paid provider backend for the orchestration eval harness.

Construction refuses unless a spend cap greater than zero is given. The API
key is read only when a model is built, from an env var or a key file path
passed at run time. Importing this module never loads a key, and
:meth:`describe` never returns one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from yarvelle_core.testing.orch_eval.backends import CostTable, Role
from yarvelle_core.testing.orch_eval.cost import (
    SpendMeter,
    SpendRefusedError,
    cost_table_for,
    load_cost_tables,
    require_paid_budget,
)
from yarvelle_core.testing.orch_eval.defaults import (
    DEFAULT_PROVIDER,
    DEFAULT_PROVIDER_JUDGE_MODEL,
    DEFAULT_PROVIDER_SUBJECT_MODEL,
    DEFAULT_SEED,
    DEFAULT_TEMPERATURE,
)

# Env vars consulted at model-build time only (never at import).
_KEY_ENV_BY_PROVIDER = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "custom": ("CUSTOM_API_KEY",),
}


def _read_key(provider: str, key_file: Optional[str]) -> Optional[str]:
    if key_file:
        path = Path(key_file).expanduser()
        if not path.is_file():
            raise SpendRefusedError(f"key file not found: {key_file}")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise SpendRefusedError(f"key file is empty: {key_file}")
        return value
    for var in _KEY_ENV_BY_PROVIDER.get(provider, ()):
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return None


class ProviderBackend:
    """Metered OpenAI-compatible (or other) provider behind :class:`EvalBackend`."""

    name = "provider"

    def __init__(
        self,
        *,
        max_usd: Optional[float],
        provider: str = DEFAULT_PROVIDER,
        subject_model: str = DEFAULT_PROVIDER_SUBJECT_MODEL,
        judge_model: str = DEFAULT_PROVIDER_JUDGE_MODEL,
        key_file: Optional[str] = None,
        base_url: Optional[str] = None,
        seed: int = DEFAULT_SEED,
        temperature: float = DEFAULT_TEMPERATURE,
        load_key: bool = True,
    ) -> None:
        self.max_usd = require_paid_budget(max_usd, backend=self.name)
        self.provider = provider
        self.subject_model = subject_model
        self.judge_model = judge_model
        self.key_file = key_file
        self.base_url = base_url
        self.seed = seed
        self.temperature = temperature
        self._tables = load_cost_tables()
        self.cost_per_mtok: CostTable = cost_table_for(subject_model, self._tables)
        self.meter = SpendMeter(max_usd=self.max_usd)
        self._key: Optional[str] = None
        self._models: Dict[str, Any] = {}
        if load_key:
            self._key = _read_key(provider, key_file)
            if not self._key:
                vars_ = ", ".join(_KEY_ENV_BY_PROVIDER.get(provider, ())) or "(none)"
                raise SpendRefusedError(
                    f"no API key for provider {provider!r}. Pass --key-file or set one of: {vars_}. "
                    f"Keys are never logged or written to reports."
                )

    def model_for(self, role: Role) -> Any:
        key = "judge" if role.kind == "judge" else "subject"
        if key in self._models:
            return self._models[key]
        if self.meter.stopped:
            raise SpendRefusedError(self.meter.stop_reason or "spend cap reached")
        from yarvelle_core.model.factory import create_chat_model

        name = self.judge_model if key == "judge" else self.subject_model
        kwargs: Dict[str, Any] = {
            "provider": self.provider,
            "model": name,
            "temperature": self.temperature,
            "streaming": True,
            "seed": self.seed,
        }
        if self._key:
            kwargs["api_key"] = self._key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        model = create_chat_model(**kwargs)
        self._models[key] = model
        return model

    def record_usage(self, *, model: str, input_tokens: int, output_tokens: int) -> float:
        """Records tokens against the spend meter using the local price table."""
        table = cost_table_for(model, self._tables)
        return self.meter.record(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens, table=table
        )

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "provider",
            "provider": self.provider,
            "subject_model": self.subject_model,
            "judge_model": self.judge_model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_usd": self.max_usd,
            "cost_per_mtok": {
                "input": self.cost_per_mtok.input_per_mtok,
                "output": self.cost_per_mtok.output_per_mtok,
            },
            "key_loaded": bool(self._key),
            # Never include the key or key file contents.
        }


__all__ = ["ProviderBackend"]
