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

"""Safety guard configuration (the ``safety.guards`` block in ``pack.yaml``).

A pack lists extra checks that run after its ``SafetyPolicy``:

- ``rules`` checks: regular expressions with reusable fragments, text
  normalization and exempt spans. Deterministic and cheap.
- ``model`` checks: a chat model the user configures (a guard model, a
  self-trained classifier served behind a chat endpoint, or a judge prompt).
  Core never ships or downloads a model. Endpoints come from environment
  variables (see ``yarvelle_core.engine.guards.env``) or the pack's ``model``
  block, and are built with the same LangChain factory as every other model.

The pack's ``SafetyPolicy`` always runs first. A guard can add a refusal but
can never turn a policy refusal into an allowed answer. The module is
data-only; behaviour lives in ``yarvelle_core.engine.guards``.
"""

from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GUARD_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"
BLOCK_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_GUARD_CHECKS = 16
MAX_TEMPLATE_CHARS = 8000

GuardStage = Literal["input", "output"]
GuardMode = Literal["enforce", "shadow", "off"]
GuardFailAction = Literal["block", "refuse", "allow"]  # refuse is read as block
GuardBlockAction = Literal["refuse", "warn"]
GuardPreset = Literal["llama_guard", "granite_guardian", "labels", "json"]
GuardStyle = Literal["moderation", "prompt"]
GuardRelease = Literal["stream", "buffered"]
RegexFlag = Literal["ignorecase", "multiline", "dotall"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_regex(value: str, what: str) -> str:
    try:
        re.compile(value)
    except re.error as err:
        raise ValueError(f"invalid {what} regex {value!r}: {err}") from err
    return value


class RulePatternSpec(_Strict):
    """One pattern of a ``rules`` check. A match blocks the text."""

    id: str = Field(..., pattern=GUARD_ID_PATTERN, description="Pattern id, reported in audit records.")
    pattern: str = Field(..., min_length=1, description="Regex. <NAME> inserts a fragment from `blocks`.")
    category: Optional[str] = Field(
        default=None, pattern=GUARD_ID_PATTERN, description="Refusal category; defaults to the pattern id."
    )
    scope: Literal["text", "sentence"] = Field(
        default="text",
        description="text: search the whole text; sentence: search each sentence (see sentence_split).",
    )
    flags: List[RegexFlag] = Field(default_factory=lambda: ["ignorecase"], description="Regex flags.")


class RuleNormalizeSpec(_Strict):
    """A regex substitution applied to the text before patterns are checked."""

    pattern: str = Field(..., min_length=1)
    replace: str = Field(default="")

    @field_validator("pattern")
    @classmethod
    def _valid(cls, v: str) -> str:
        return _check_regex(v, "normalize")


class ModelEndpointSpec(_Strict):
    """Where a model check's model runs. Environment variables override every field."""

    provider: Optional[str] = Field(default=None, description="Model provider, e.g. ollama, openai, custom.")
    model: Optional[str] = Field(default=None, description="Model name at the provider.")
    base_url: Optional[str] = Field(default=None, description="Endpoint URL for ollama or custom providers.")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class ModelOutputSpec(_Strict):
    """How a model check reads the model's reply.

    ``labels``: the first word of the reply is matched against ``allow_labels``
    and ``block_labels`` (case-insensitive). Categories are read from the rest
    of the first line or the next line, comma separated.

    ``json``: the first JSON object in the reply is read. ``decision`` is
    matched against the same labels; ``abstain_labels`` mean the model is not
    sure. With ``block_threshold`` / ``allow_threshold`` set, ``score``
    decides instead: at or above block_threshold blocks, at or below
    allow_threshold allows, in between abstains.

    Anything else is an unreadable reply and counts as an error.
    """

    format: Literal["labels", "json"] = "labels"
    allow_labels: List[str] = Field(default_factory=lambda: ["safe", "allow"])
    block_labels: List[str] = Field(default_factory=lambda: ["unsafe", "block"])
    abstain_labels: List[str] = Field(default_factory=lambda: ["abstain", "unsure", "uncertain"])
    decision_key: str = "decision"
    category_key: str = "category"
    score_key: str = "score"
    block_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    allow_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    block_categories: List[str] = Field(
        default_factory=list,
        description=(
            "When set, a block verdict counts only if the model names one of these categories; "
            "other categories are allowed and recorded."
        ),
    )

    @model_validator(mode="after")
    def _labels(self) -> "ModelOutputSpec":
        allow = {s.strip().lower() for s in self.allow_labels}
        block = {s.strip().lower() for s in self.block_labels}
        if not allow or not block:
            raise ValueError("allow_labels and block_labels must not be empty")
        if allow & block:
            raise ValueError(f"labels cannot both allow and block: {sorted(allow & block)}")
        if (
            self.block_threshold is not None
            and self.allow_threshold is not None
            and self.allow_threshold > self.block_threshold
        ):
            raise ValueError("allow_threshold must not exceed block_threshold")
        return self


class GuardCheckSpec(_Strict):
    """One guard check (an entry of ``safety.guards.checks``)."""

    id: str = Field(..., pattern=GUARD_ID_PATTERN, description="Check id; also names its environment variables.")
    type: Literal["rules", "model"]
    stages: Optional[List[GuardStage]] = Field(
        default=None, description="When the check runs. Default: rules both stages, model output only."
    )
    mode: GuardMode = Field(
        default="enforce",
        description="enforce: the verdict counts; shadow: run and audit only; off: do not run.",
    )
    required: bool = Field(
        default=False,
        description="A required check cannot be switched to shadow or off by environment variables.",
    )
    on_block: GuardBlockAction = Field(
        default="refuse", description="refuse: replace the answer; warn: keep it and flag a boundary warning."
    )

    # rules checks
    blocks: Dict[str, Union[str, List[str]]] = Field(
        default_factory=dict,
        description="Named regex fragments. <NAME> in a pattern inserts one; a list becomes (?:a|b).",
    )
    normalize: List[RuleNormalizeSpec] = Field(default_factory=list)
    exempt: List[str] = Field(
        default_factory=list, description="Regexes whose matches are blanked out before patterns are checked."
    )
    patterns: List[RulePatternSpec] = Field(default_factory=list)
    sentence_split: Optional[str] = Field(default=None, description="Regex splitting text into sentences.")
    rules_file: Optional[str] = Field(
        default=None, description="Pack resource (YAML) with blocks/normalize/exempt/patterns/sentence_split."
    )
    max_chars: int = Field(
        default=100_000, ge=1, le=1_000_000,
        description="Longer text is not checked and counts as unchecked (blocked unless on_abstain is allow).",
    )

    # model checks
    preset: Optional[GuardPreset] = Field(default=None, description="Defaults for a known guard reply format.")
    style: Optional[GuardStyle] = Field(
        default=None,
        description=(
            "moderation: send the conversation (user message, then answer) as chat messages; "
            "prompt: send one message built from `prompt`."
        ),
    )
    system: Optional[str] = Field(default=None, max_length=MAX_TEMPLATE_CHARS, description="Optional system message.")
    prompt: Optional[str] = Field(
        default=None,
        max_length=MAX_TEMPLATE_CHARS,
        description="Template for style=prompt. {{text}}, {{prompt}} and {{stage}} are replaced.",
    )
    prompt_file: Optional[str] = Field(default=None, description="Pack resource holding the prompt template.")
    output: Optional[ModelOutputSpec] = None
    model: ModelEndpointSpec = Field(default_factory=ModelEndpointSpec)
    timeout_s: float = Field(default=10.0, gt=0, le=120)
    include_prompt: bool = Field(
        default=True, description="On the output stage, also send the user's message as context."
    )
    when_unconfigured: GuardFailAction = Field(
        default="allow",
        description=(
            "No model configured: allow skips the check (a warning names it at startup); "
            "block or refuse refuses every answer it would check."
        ),
    )
    on_abstain: GuardFailAction = Field(default="block", description="Model not sure, or text too long.")
    on_error: GuardFailAction = Field(default="block", description="Timeout, failed call or unreadable reply.")

    @field_validator("when_unconfigured", "on_abstain", "on_error")
    @classmethod
    def _refuse_means_block(cls, value: str) -> str:
        return "block" if value == "refuse" else value

    @model_validator(mode="after")
    def _consistent(self) -> "GuardCheckSpec":
        model_fields = ("preset", "style", "system", "prompt", "prompt_file", "output")
        rule_fields = ("blocks", "normalize", "exempt", "patterns", "sentence_split", "rules_file")
        if self.type == "rules":
            used = [f for f in model_fields if getattr(self, f)]
            if used or self.model != ModelEndpointSpec():
                raise ValueError(f"rules check '{self.id}' cannot set model fields: {used or ['model']}")
            if not self.patterns and not self.rules_file:
                raise ValueError(f"rules check '{self.id}' needs patterns or rules_file")
            for name in self.blocks:
                if not BLOCK_NAME_PATTERN.match(name):
                    raise ValueError(f"block name '{name}' must be UPPER_SNAKE_CASE")
            for value in self.exempt:
                _check_regex(value, "exempt")
            if self.sentence_split:
                _check_regex(self.sentence_split, "sentence_split")
        else:
            used = [f for f in rule_fields if getattr(self, f)]
            if used:
                raise ValueError(f"model check '{self.id}' cannot set rules fields: {used}")
            if self.prompt and self.prompt_file:
                raise ValueError(f"model check '{self.id}': set prompt or prompt_file, not both")
            if self.style == "prompt" and not (self.prompt or self.prompt_file):
                raise ValueError(f"model check '{self.id}': style prompt needs prompt or prompt_file")
        if self.stages is not None and not self.stages:
            raise ValueError(f"check '{self.id}': stages must not be empty")
        return self

    def effective_stages(self) -> List[str]:
        if self.stages:
            return list(dict.fromkeys(self.stages))
        return ["input", "output"] if self.type == "rules" else ["output"]


class SafetyGuardsSpec(_Strict):
    """Guard checks and how their answers are released (``safety.guards``)."""

    checks: List[GuardCheckSpec] = Field(default_factory=list, max_length=MAX_GUARD_CHECKS)
    deadline_s: float = Field(
        default=20.0, gt=0, le=300, description="Wall-clock budget for all model checks of one text."
    )
    refusal_template: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Text shown when a guard refuses. Default: the safety policy's refusal template.",
    )
    release: GuardRelease = Field(
        default="stream",
        description=(
            "stream: send answer tokens as they are generated (done carries the verdict); "
            "buffered: send the answer only after the final check passes."
        ),
    )

    @model_validator(mode="after")
    def _unique(self) -> "SafetyGuardsSpec":
        seen: set[str] = set()
        for check in self.checks:
            if check.id in seen:
                raise ValueError(f"duplicate guard check id '{check.id}'")
            seen.add(check.id)
        if self.refusal_template is not None and not self.refusal_template.strip():
            raise ValueError("refusal_template must not be blank")
        return self


class PackSafetySpec(_Strict):
    """The ``safety`` block of ``pack.yaml``."""

    guards: Optional[SafetyGuardsSpec] = None


__all__ = [
    "GUARD_ID_PATTERN",
    "GuardCheckSpec",
    "GuardMode",
    "GuardStage",
    "ModelEndpointSpec",
    "ModelOutputSpec",
    "PackSafetySpec",
    "RuleNormalizeSpec",
    "RulePatternSpec",
    "SafetyGuardsSpec",
]
