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

"""Reading a guard model's reply (``output.format``: labels or json).

Both readers return a decision plus categories and an optional score. A reply
that cannot be read is an ERROR, never an allow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from yarvelle_core.engine.guards.types import GuardDecision
from yarvelle_core.schemas.safety import ModelOutputSpec

_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


@dataclass(frozen=True)
class ParsedReply:
    decision: GuardDecision
    categories: Tuple[str, ...] = ()
    score: Optional[float] = None
    detail: Optional[str] = None


def reply_text(content: Any) -> str:
    """Text of a chat model reply; list content keeps only text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return "" if content is None else str(content)


def _strip_reasoning(text: str) -> Optional[str]:
    out = _THINK.sub("", text)
    if re.search(r"<think>", out, re.IGNORECASE):
        return None  # unterminated reasoning block
    return out


def _norm(labels: List[str]) -> set[str]:
    return {s.strip().lower() for s in labels if s.strip()}


def _split_categories(raw: str) -> Tuple[str, ...]:
    items = [c.strip().strip(".:;\"'`*") for c in re.split(r"[,\n]", raw)]
    return tuple(c for c in items if c)


def parse_labels(text: str, spec: ModelOutputSpec) -> ParsedReply:
    body = _strip_reasoning(text)
    if body is None:
        return ParsedReply(GuardDecision.ERROR, detail="unreadable_reply")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return ParsedReply(GuardDecision.ERROR, detail="empty_reply")
    first = lines[0].lstrip("*_`#> ")
    m = _WORD.match(first)
    if not m:
        return ParsedReply(GuardDecision.ERROR, detail="unreadable_reply")
    label = m.group(0).lower()
    rest = first[m.end():].strip(" :-,.")
    if label in _norm(spec.block_labels):
        raw = rest or (lines[1] if len(lines) > 1 else "")
        return ParsedReply(GuardDecision.BLOCK, categories=_split_categories(raw))
    if label in _norm(spec.allow_labels):
        return ParsedReply(GuardDecision.ALLOW)
    if label in _norm(spec.abstain_labels):
        return ParsedReply(GuardDecision.ABSTAIN, detail="model_abstained")
    return ParsedReply(GuardDecision.ERROR, detail="unknown_label")


def _first_json_object(text: str) -> Optional[dict]:
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except ValueError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            return obj
        idx = text.find("{", idx + 1)
    return None


def parse_json(text: str, spec: ModelOutputSpec) -> ParsedReply:
    body = _strip_reasoning(text)
    if body is None:
        return ParsedReply(GuardDecision.ERROR, detail="unreadable_reply")
    obj = _first_json_object(body)
    if obj is None:
        return ParsedReply(GuardDecision.ERROR, detail="no_json_object")
    raw_cat = obj.get(spec.category_key)
    if isinstance(raw_cat, list):
        categories = tuple(str(c).strip() for c in raw_cat if str(c).strip())
    elif raw_cat:
        categories = _split_categories(str(raw_cat))
    else:
        categories = ()
    score: Optional[float] = None
    if spec.score_key in obj and obj[spec.score_key] is not None:
        try:
            score = float(obj[spec.score_key])
        except (TypeError, ValueError):
            return ParsedReply(GuardDecision.ERROR, detail="invalid_score")
        if not 0.0 <= score <= 1.0 or score != score:
            return ParsedReply(GuardDecision.ERROR, detail="invalid_score")
    if spec.block_threshold is not None or spec.allow_threshold is not None:
        if score is None:
            return ParsedReply(GuardDecision.ERROR, detail="missing_score")
        if spec.block_threshold is not None and score >= spec.block_threshold:
            return ParsedReply(GuardDecision.BLOCK, categories=categories, score=score)
        if spec.allow_threshold is not None and score <= spec.allow_threshold:
            return ParsedReply(GuardDecision.ALLOW, score=score)
        return ParsedReply(GuardDecision.ABSTAIN, categories=categories, score=score, detail="score_between_thresholds")
    decision = str(obj.get(spec.decision_key, "")).strip().lower()
    if decision in _norm(spec.block_labels):
        return ParsedReply(GuardDecision.BLOCK, categories=categories, score=score)
    if decision in _norm(spec.allow_labels):
        return ParsedReply(GuardDecision.ALLOW, score=score)
    if decision in _norm(spec.abstain_labels):
        return ParsedReply(GuardDecision.ABSTAIN, categories=categories, score=score, detail="model_abstained")
    return ParsedReply(GuardDecision.ERROR, detail="unknown_decision")


def parse_reply(text: str, spec: ModelOutputSpec) -> ParsedReply:
    parsed = parse_json(text, spec) if spec.format == "json" else parse_labels(text, spec)
    if parsed.decision == GuardDecision.BLOCK and spec.block_categories:
        wanted = _norm(spec.block_categories)
        if not any(c.lower() in wanted for c in parsed.categories):
            return ParsedReply(
                GuardDecision.ALLOW, categories=parsed.categories, score=parsed.score,
                detail="category_not_selected",
            )
    return parsed


__all__ = ["ParsedReply", "parse_json", "parse_labels", "parse_reply", "reply_text"]
