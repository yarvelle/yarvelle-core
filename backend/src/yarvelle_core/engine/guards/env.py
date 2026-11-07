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

"""Environment variables for guard checks.

Names use core's prefix (``YARVELLE_`` unless ``YARVELLE_ENV_PREFIX`` says
otherwise; see ``yarvelle_core.identity``). ``<ID>`` is the check id in upper
case with ``-`` written as ``_``.

Per check (pack-declared or env-only):

- ``<PREFIX>_SAFETY_GUARD_<ID>_PROVIDER``  model provider (ollama, openai, anthropic, google, custom)
- ``<PREFIX>_SAFETY_GUARD_<ID>_MODEL``     model name at that provider
- ``<PREFIX>_SAFETY_GUARD_<ID>_BASE_URL``  endpoint for ollama/custom providers
- ``<PREFIX>_SAFETY_GUARD_<ID>_TIMEOUT_S`` per-call timeout in seconds
- ``<PREFIX>_SAFETY_GUARD_<ID>_MODE``      enforce | shadow | off (ignored for a required check)

API keys are the provider's usual variables (``OPENAI_API_KEY`` and so on),
read by the model factory, never by guards.

Checks without pack YAML: ``<PREFIX>_SAFETY_GUARDS`` lists check ids
(comma separated). Each needs ``_PRESET`` (llama_guard or granite_guardian),
``_PROVIDER`` and ``_MODEL``; optional ``_STAGES`` (input,output),
``_SYSTEM`` and ``_MODE`` (default shadow). Env-only checks can only add
refusals; they never replace or loosen a pack's checks.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from yarvelle_core import identity
from yarvelle_core.schemas.safety import GUARD_ID_PATTERN, GuardCheckSpec, ModelEndpointSpec

ENV_GUARDS = "SAFETY_GUARDS"
_ID_RE = re.compile(GUARD_ID_PATTERN)
ENV_ONLY_PRESETS = ("llama_guard", "granite_guardian")


class GuardEnvError(ValueError):
    """Guard environment variables are inconsistent."""


def env_token(check_id: str) -> str:
    return check_id.upper().replace("-", "_")


def guard_env_suffix(check_id: str, field: str) -> str:
    return f"SAFETY_GUARD_{env_token(check_id)}_{field}"


def guard_env_name(check_id: str, field: str) -> str:
    """Full variable name under the active prefix, for messages and docs."""
    return identity.env_name(guard_env_suffix(check_id, field))


def read_guard_env(check_id: str, field: str) -> Optional[str]:
    return identity.getenv(guard_env_suffix(check_id, field))


def resolve_endpoint(spec: GuardCheckSpec) -> ModelEndpointSpec:
    """The pack's ``model`` block with environment overrides applied."""
    base = spec.model
    return ModelEndpointSpec(
        provider=read_guard_env(spec.id, "PROVIDER") or base.provider,
        model=read_guard_env(spec.id, "MODEL") or base.model,
        base_url=read_guard_env(spec.id, "BASE_URL") or base.base_url,
        temperature=base.temperature,
    )


def resolve_timeout(spec: GuardCheckSpec) -> float:
    raw = read_guard_env(spec.id, "TIMEOUT_S")
    if raw is None:
        return spec.timeout_s
    try:
        value = float(raw)
    except ValueError as err:
        raise GuardEnvError(f"{guard_env_name(spec.id, 'TIMEOUT_S')} must be a number, got {raw!r}") from err
    if not 0 < value <= 120:
        raise GuardEnvError(f"{guard_env_name(spec.id, 'TIMEOUT_S')} must be in (0, 120], got {raw!r}")
    return value


def resolve_mode(spec: GuardCheckSpec) -> str:
    """Pack mode, or the env override. A required check always stays enforce."""
    raw = read_guard_env(spec.id, "MODE")
    if raw is None:
        return spec.mode
    mode = raw.strip().lower()
    if mode not in ("enforce", "shadow", "off"):
        raise GuardEnvError(f"{guard_env_name(spec.id, 'MODE')} must be enforce, shadow or off, got {raw!r}")
    if spec.required and spec.mode == "enforce":
        return "enforce"
    return mode


def env_only_checks(existing_ids: Optional[List[str]] = None) -> List[GuardCheckSpec]:
    """Checks declared only through ``<PREFIX>_SAFETY_GUARDS``.

    An id the pack already declares is skipped here: its endpoint variables
    configure the pack's check instead.
    """
    raw = identity.getenv(ENV_GUARDS)
    if not raw:
        return []
    taken = set(existing_ids or [])
    out: List[GuardCheckSpec] = []
    seen: set[str] = set()
    for item in raw.split(","):
        check_id = item.strip().lower()
        if not check_id or check_id in taken or check_id in seen:
            continue
        if not _ID_RE.match(check_id):
            raise GuardEnvError(f"{identity.env_name(ENV_GUARDS)}: invalid check id {item!r}")
        seen.add(check_id)
        preset = (read_guard_env(check_id, "PRESET") or "").strip().lower()
        if preset not in ENV_ONLY_PRESETS:
            raise GuardEnvError(
                f"{guard_env_name(check_id, 'PRESET')} must be one of {', '.join(ENV_ONLY_PRESETS)}"
            )
        stages_raw = read_guard_env(check_id, "STAGES") or "output"
        stages = [s.strip().lower() for s in stages_raw.split(",") if s.strip()]
        mode = (read_guard_env(check_id, "MODE") or "shadow").strip().lower()
        data: Dict[str, object] = {
            "id": check_id,
            "type": "model",
            "preset": preset,
            "stages": stages,
            "mode": mode,
            # Named explicitly by the user, so a missing endpoint is a mistake.
            "when_unconfigured": "block" if mode == "enforce" else "allow",
        }
        system = read_guard_env(check_id, "SYSTEM")
        if system:
            data["system"] = system
        try:
            out.append(GuardCheckSpec.model_validate(data))
        except Exception as err:
            raise GuardEnvError(f"env guard '{check_id}' is invalid: {err}") from err
    return out


__all__ = [
    "ENV_GUARDS",
    "GuardEnvError",
    "env_only_checks",
    "guard_env_name",
    "read_guard_env",
    "resolve_endpoint",
    "resolve_mode",
    "resolve_timeout",
]
