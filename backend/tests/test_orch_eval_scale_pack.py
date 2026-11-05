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

"""The forty-agent eval pack stays neutral and keeps its catalog short."""

from __future__ import annotations

from pathlib import Path

import pytest

from yarvelle_core.engine.orchestration.runtime import compose_main_prompt
from yarvelle_core.testing.orch_eval.pack import load_eval_pack

PACK_DIR = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "orchestration"
    / "packs"
    / "eval-scale-40"
)

# Soft bound used by scale scenarios' budget.prompt_chars.
PROMPT_CHAR_BUDGET = 20000


@pytest.mark.skipif(not PACK_DIR.is_dir(), reason="scale pack not present in this checkout")
def test_scale_pack_has_forty_neutral_agents_and_bounded_catalog():
    pack = load_eval_pack(PACK_DIR)
    assert pack.id == "eval-scale-40"
    assert len(pack.agent_ids) == 40
    assert "internal-reviewer" in pack.hidden_ids
    assert "desk-assistant" == pack.spec.default_agent
    blob = " ".join(
        f"{a.id} {a.title} {pack.registry.get(a.id).description or ''}"
        for a in pack.registry.list_agents()
    ).lower()
    for banned in ("doctor", "patient", "clinic", "carefold", "diagnos", "prescri", "homework"):
        assert banned not in blob, banned
    catalog = sum(
        len(str(spec.get("name") or "")) + len(str(spec.get("description") or ""))
        for spec in pack.registry.list_subagents()
    )
    prompt_chars = len(compose_main_prompt(None, getattr(pack.spec, "synthesis", None))) + catalog
    assert prompt_chars <= PROMPT_CHAR_BUDGET, prompt_chars
    assert prompt_chars > 0
