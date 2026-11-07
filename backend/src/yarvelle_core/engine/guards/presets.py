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

"""Reply-format presets for well-known guard model families.

A preset only says how to talk to a model and read its reply. It does not
name, ship or download a model: which model runs is the user's choice.

- ``llama_guard``: chat-template moderation; reply ``safe`` or
  ``unsafe`` followed by category codes on the next line.
- ``granite_guardian``: chat-template moderation; reply ``Yes`` (risk found)
  or ``No``. The risk to test is usually given in ``system``.
- ``labels``: a pack prompt; reply starts with an allow or block label.
- ``json``: a pack prompt; reply holds a JSON object (decision, category, score).

Generic guard taxonomies are not the pack's policy; validate any model on
the pack's own labelled examples before giving it enforce mode.
"""

from __future__ import annotations

from typing import Dict, Tuple

from yarvelle_core.schemas.safety import GuardCheckSpec, ModelOutputSpec

PRESETS: Dict[str, Tuple[str, ModelOutputSpec]] = {
    "llama_guard": ("moderation", ModelOutputSpec(format="labels", allow_labels=["safe"], block_labels=["unsafe"])),
    "granite_guardian": ("moderation", ModelOutputSpec(format="labels", allow_labels=["no"], block_labels=["yes"])),
    "labels": ("prompt", ModelOutputSpec(format="labels")),
    "json": ("prompt", ModelOutputSpec(format="json")),
}


def resolve_style_and_output(spec: GuardCheckSpec) -> Tuple[str, ModelOutputSpec]:
    """Explicit style/output win; then the preset; then moderation with labels."""
    preset_style, preset_output = PRESETS.get(spec.preset or "", (None, None))
    style = spec.style or preset_style or ("prompt" if (spec.prompt or spec.prompt_file) else "moderation")
    output = spec.output or preset_output or ModelOutputSpec()
    return style, output


__all__ = ["PRESETS", "resolve_style_and_output"]
