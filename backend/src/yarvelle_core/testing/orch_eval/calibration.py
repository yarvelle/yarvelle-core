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

"""Labelled judge calibration cases and agreement measurement.

Cases under ``backend/evals/orchestration/calibration/`` are **human-style
labels** written as fixtures. They are not model output. Each file must set
``kind: human_label`` so tooling never treats them as recordings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from yarvelle_core.testing.orch_eval.judge import (
    DEFAULT_JUDGE_SAMPLES,
    MIN_AGREEMENT_FOR_GATE,
    AggregatedJudgeResult,
    score_turn,
)
from yarvelle_core.testing.orch_eval.report import default_out_root

DEFAULT_CALIBRATION_DIR = (
    Path(__file__).resolve().parents[4] / "evals" / "orchestration" / "calibration"
)
# When installed as a package the parents walk may not hit the repo; callers
# should pass an explicit directory. The CLI resolves relative to the repo.


class CalibrationCase(BaseModel):
    """One labelled turn used to measure judge agreement."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, alias="schema")
    id: str = Field(..., min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    kind: str = Field(..., pattern=r"^human_label$")
    rubric: str = Field(..., pattern=r"^[a-z0-9_-]{1,64}$")
    criteria: str = Field(..., min_length=1)
    user: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    conversation: List[Dict[str, str]] = Field(default_factory=list)
    trace_summary: Dict[str, Any] = Field(default_factory=dict)
    label: "HumanLabel"
    notes: str = ""

    @field_validator("kind")
    @classmethod
    def _kind_is_label(cls, value: str) -> str:
        if value != "human_label":
            raise ValueError("calibration fixtures must set kind: human_label")
        return value


class HumanLabel(BaseModel):
    """Human score/verdict for a calibration case (not model output)."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(..., ge=1, le=5)
    verdict: str = Field(..., pattern=r"^(pass|fail)$")
    notes: str = ""


CalibrationCase.model_rebuild()


def default_calibration_dir() -> Path:
    """Best-effort path to committed calibration fixtures in a source checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "evals" / "orchestration" / "calibration"
        if candidate.is_dir():
            return candidate
        candidate = parent / "backend" / "evals" / "orchestration" / "calibration"
        if candidate.is_dir():
            return candidate
    return DEFAULT_CALIBRATION_DIR


def load_calibration_case(path: Path) -> CalibrationCase:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: expected a mapping")
    case = CalibrationCase.model_validate(raw)
    if case.kind != "human_label":
        raise ValueError(f"{path}: kind must be human_label (got {case.kind!r})")
    return case


def load_calibration_dir(root: Path) -> List[CalibrationCase]:
    if not root.is_dir():
        raise FileNotFoundError(f"calibration directory not found: {root}")
    cases: List[CalibrationCase] = []
    for path in sorted(root.glob("*.yaml")):
        cases.append(load_calibration_case(path))
    if not cases:
        raise FileNotFoundError(f"no calibration YAML files in {root}")
    return cases


@dataclass
class CaseAgreement:
    case_id: str
    label_verdict: str
    label_score: int
    judge_verdict: str
    judge_score: int
    agreed: bool
    unsure: bool
    judge: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgreementReport:
    judge_model: str
    backend: str
    samples: int
    cases: List[CaseAgreement]
    agreement: float
    cohen_kappa: float
    n: int
    n_agree: int
    meets_gate_threshold: bool
    measured_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "judge_model": self.judge_model,
            "backend": self.backend,
            "samples": self.samples,
            "agreement": self.agreement,
            "cohen_kappa": self.cohen_kappa,
            "n": self.n,
            "n_agree": self.n_agree,
            "meets_gate_threshold": self.meets_gate_threshold,
            "gate_threshold": MIN_AGREEMENT_FOR_GATE,
            "measured_at": self.measured_at,
            "cases": [c.to_dict() for c in self.cases],
            "kind_note": (
                "Labels are human_label fixtures, not model output. "
                "Judge samples are model output."
            ),
        }


def cohen_kappa(labels: Sequence[str], preds: Sequence[str]) -> float:
    """Cohen's kappa for binary (or multi-class) string labels."""
    if len(labels) != len(preds) or not labels:
        return 0.0
    n = len(labels)
    classes = sorted(set(labels) | set(preds))
    # observed agreement
    po = sum(1 for a, b in zip(labels, preds) if a == b) / n
    # expected agreement
    pe = 0.0
    for cls in classes:
        pe += (sum(1 for x in labels if x == cls) / n) * (
            sum(1 for x in preds if x == cls) / n
        )
    if abs(1.0 - pe) < 1e-12:
        return 1.0 if po >= 1.0 - 1e-12 else 0.0
    return (po - pe) / (1.0 - pe)


def verdict_matches(label_verdict: str, judge_verdict: str, *, unsure: bool) -> bool:
    """Agreement ignores unsure judge outcomes (counts as disagreement)."""
    if unsure or judge_verdict == "unsure":
        return False
    return label_verdict == judge_verdict


def measure_agreement(
    cases: Sequence[CalibrationCase],
    model: Any,
    *,
    judge_model: str,
    backend: str = "ollama",
    samples: int = DEFAULT_JUDGE_SAMPLES,
    rubrics_dir: Optional[Path] = None,
) -> AgreementReport:
    """Score each labelled case and compute agreement vs human labels."""
    rows: List[CaseAgreement] = []
    for case in cases:
        result: AggregatedJudgeResult = score_turn(
            model,
            rubric=case.rubric,
            criteria=case.criteria,
            min_score=4,
            user=case.user,
            answer=case.answer,
            trace_summary=case.trace_summary,
            conversation=case.conversation,
            samples=samples,
            rubrics_dir=rubrics_dir,
        )
        agreed = verdict_matches(
            case.label.verdict, result.verdict, unsure=result.unsure
        )
        rows.append(
            CaseAgreement(
                case_id=case.id,
                label_verdict=case.label.verdict,
                label_score=case.label.score,
                judge_verdict=result.verdict,
                judge_score=result.score,
                agreed=agreed,
                unsure=result.unsure,
                judge=result.to_dict(),
            )
        )
    n = len(rows)
    n_agree = sum(1 for r in rows if r.agreed)
    agreement = (n_agree / n) if n else 0.0
    # For kappa, map unsure -> distinct class so it reduces chance agreement.
    label_v = [r.label_verdict for r in rows]
    pred_v = ["unsure" if r.unsure else r.judge_verdict for r in rows]
    kappa = cohen_kappa(label_v, pred_v)
    return AgreementReport(
        judge_model=judge_model,
        backend=backend,
        samples=samples,
        cases=rows,
        agreement=agreement,
        cohen_kappa=kappa,
        n=n,
        n_agree=n_agree,
        meets_gate_threshold=agreement >= MIN_AGREEMENT_FOR_GATE,
        measured_at=datetime.now(timezone.utc).isoformat(),
    )


def calibration_store_path(
    judge_model: str,
    *,
    backend: str = "ollama",
    root: Optional[Path] = None,
) -> Path:
    base = root or (default_out_root() / "calibration")
    safe_model = "".join(c if c.isalnum() or c in "-._" else "-" for c in judge_model)
    safe_backend = "".join(c if c.isalnum() or c in "-._" else "-" for c in backend)
    return base / f"{safe_backend}-{safe_model}.json"


def save_agreement_report(report: AgreementReport, path: Optional[Path] = None) -> Path:
    target = path or calibration_store_path(report.judge_model, backend=report.backend)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return target


def load_agreement_report(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def resolve_stored_agreement(
    judge_model: str,
    *,
    backend: str = "ollama",
    root: Optional[Path] = None,
    explicit: Optional[float] = None,
) -> Optional[float]:
    """Return an explicit agreement override, or the last saved measurement."""
    if explicit is not None:
        return float(explicit)
    path = calibration_store_path(judge_model, backend=backend, root=root)
    if not path.is_file():
        return None
    data = load_agreement_report(path)
    value = data.get("agreement")
    return float(value) if value is not None else None


__all__ = [
    "AgreementReport",
    "CalibrationCase",
    "CaseAgreement",
    "HumanLabel",
    "calibration_store_path",
    "cohen_kappa",
    "default_calibration_dir",
    "load_agreement_report",
    "load_calibration_case",
    "load_calibration_dir",
    "measure_agreement",
    "resolve_stored_agreement",
    "save_agreement_report",
    "verdict_matches",
]
