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

"""Deterministic regex guard checks (``type: rules``).

Order of work for each text:

1. ``normalize`` substitutions, in order (strip markup, unify quotes, ...).
2. ``exempt`` matches are replaced by spaces of the same length, so exempt
   wording (a quoted warning, a disclaimer) cannot trigger a pattern and
   offsets stay stable.
3. ``scope: text`` patterns search the whole text; ``scope: sentence``
   patterns search each sentence from ``sentence_split``.

The first matching pattern blocks. ``<NAME>`` in any regex inserts the
``blocks`` fragment of that name; fragments may use earlier fragments, and a
list fragment becomes one group of alternatives, ``(?:a|b)``.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from yarvelle_core.engine.guards.env import resolve_mode
from yarvelle_core.engine.guards.types import GuardDecision, GuardRequest, GuardResult
from yarvelle_core.schemas.safety import GuardCheckSpec, RuleNormalizeSpec, RulePatternSpec

_TAG = re.compile(r"<([A-Z][A-Z0-9_]{0,63})>")
_FLAG_BITS = {"ignorecase": re.IGNORECASE, "multiline": re.MULTILINE, "dotall": re.DOTALL}
DEFAULT_SENTENCE_SPLIT = r"(?<=[.!?])\s+|\n+"


class RulesConfigError(ValueError):
    """A rules check could not be compiled."""


def resolve_blocks(blocks: Mapping[str, Any]) -> Dict[str, str]:
    """Expands fragments in declaration order. An unknown <NAME> is an error."""
    resolved: Dict[str, str] = {}
    for name, raw in blocks.items():
        value = "(?:" + "|".join(str(v) for v in raw) + ")" if isinstance(raw, (list, tuple)) else str(raw)
        resolved[name] = _expand(value, resolved, where=f"block {name}")
    return resolved


def _expand(pattern: str, blocks: Mapping[str, str], *, where: str) -> str:
    def sub(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name not in blocks:
            raise RulesConfigError(f"{where}: unknown fragment <{name}>")
        return blocks[name]

    return _TAG.sub(sub, pattern)


def _compile(pattern: str, flags: int, *, where: str) -> "re.Pattern[str]":
    try:
        return re.compile(pattern, flags)
    except re.error as err:
        raise RulesConfigError(f"{where}: invalid regex: {err}") from err


class RuleCheck:
    """A compiled ``rules`` check."""

    kind = "rules"

    def __init__(self, spec: GuardCheckSpec, extra: Optional[Mapping[str, Any]] = None) -> None:
        self.spec = spec
        self.id = spec.id
        self.mode = resolve_mode(spec)
        data = _merge(spec, extra or {})
        blocks = resolve_blocks(data["blocks"])
        self._normalize: List[Tuple["re.Pattern[str]", str]] = [
            (_compile(_expand(n.pattern, blocks, where=f"{self.id} normalize"), 0, where=f"{self.id} normalize"), n.replace)
            for n in data["normalize"]
        ]
        self._exempt = [
            _compile(_expand(p, blocks, where=f"{self.id} exempt"), re.IGNORECASE, where=f"{self.id} exempt")
            for p in data["exempt"]
        ]
        split = data["sentence_split"] or DEFAULT_SENTENCE_SPLIT
        self._split = _compile(split, 0, where=f"{self.id} sentence_split")
        self._patterns: List[Tuple[RulePatternSpec, "re.Pattern[str]"]] = []
        for p in data["patterns"]:
            flags = 0
            for f in p.flags:
                flags |= _FLAG_BITS[f]
            where = f"{self.id} pattern {p.id}"
            self._patterns.append((p, _compile(_expand(p.pattern, blocks, where=where), flags, where=where)))
        if not self._patterns:
            raise RulesConfigError(f"rules check '{self.id}' has no patterns")

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)

    def prepare(self, text: str) -> str:
        """Normalized text with exempt spans blanked; what patterns are matched against."""
        out = text
        for regex, repl in self._normalize:
            out = regex.sub(repl, out)
        for regex in self._exempt:
            out = regex.sub(lambda m: " " * len(m.group(0)), out)
        return out

    def match(self, text: str) -> Optional[RulePatternSpec]:
        prepared = self.prepare(text)
        sentences: Optional[List[str]] = None
        for spec, regex in self._patterns:
            if spec.scope == "text":
                if regex.search(prepared):
                    return spec
            else:
                if sentences is None:
                    sentences = [s.strip() for s in self._split.split(prepared) if s and s.strip()]
                if any(regex.search(s) for s in sentences):
                    return spec
        return None

    def evaluate_sync(self, request: GuardRequest) -> GuardResult:
        start = time.perf_counter()
        text = request.text or ""
        if len(text) > self.spec.max_chars:
            return GuardResult(
                check_id=self.id, decision=GuardDecision.ABSTAIN, mode=self.mode,
                detail="text_too_long", latency_ms=_ms(start),
            )
        hit = self.match(text)
        if hit is None:
            return GuardResult(check_id=self.id, decision=GuardDecision.ALLOW, mode=self.mode, latency_ms=_ms(start))
        category = hit.category or hit.id
        return GuardResult(
            check_id=self.id, decision=GuardDecision.BLOCK, mode=self.mode, category=category,
            categories=(category,), detail=f"pattern:{hit.id}", latency_ms=_ms(start),
        )

    async def evaluate(self, request: GuardRequest) -> GuardResult:
        return self.evaluate_sync(request)


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


_FILE_KEYS = ("blocks", "normalize", "exempt", "patterns", "sentence_split")


def _merge(spec: GuardCheckSpec, extra: Mapping[str, Any]) -> Dict[str, Any]:
    """Inline settings plus a rules_file's. File entries come first; inline ones are added after."""
    unknown = set(extra) - set(_FILE_KEYS)
    if unknown:
        raise RulesConfigError(f"rules_file for '{spec.id}' has unknown keys: {sorted(unknown)}")
    try:
        file_blocks = dict(extra.get("blocks") or {})
        file_norm = [RuleNormalizeSpec.model_validate(n) for n in (extra.get("normalize") or [])]
        file_exempt = [str(e) for e in (extra.get("exempt") or [])]
        file_patterns = [RulePatternSpec.model_validate(p) for p in (extra.get("patterns") or [])]
    except Exception as err:  # pydantic ValidationError and type errors
        raise RulesConfigError(f"rules_file for '{spec.id}' is invalid: {err}") from err
    blocks = {**file_blocks, **spec.blocks}
    patterns = file_patterns + list(spec.patterns)
    ids = [p.id for p in patterns]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise RulesConfigError(f"rules check '{spec.id}' has duplicate pattern ids: {dupes}")
    return {
        "blocks": blocks,
        "normalize": file_norm + list(spec.normalize),
        "exempt": file_exempt + list(spec.exempt),
        "patterns": patterns,
        "sentence_split": spec.sentence_split or extra.get("sentence_split"),
    }


__all__ = ["DEFAULT_SENTENCE_SPLIT", "RuleCheck", "RulesConfigError", "resolve_blocks"]
