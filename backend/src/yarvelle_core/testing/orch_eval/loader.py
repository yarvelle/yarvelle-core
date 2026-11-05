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

"""Loads and validates orchestration eval scenarios from YAML files.

:func:`parse_scenario` validates an already-parsed mapping and has no side
effects. The file loaders refuse to run on CI before reading anything, so a
CI job cannot even enumerate scenarios.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Union

from pydantic import ValidationError
import yaml

from yarvelle_core.testing.orch_eval.guard import ensure_not_ci
from yarvelle_core.testing.orch_eval.schema import Scenario

SCENARIO_SUFFIXES = (".yaml", ".yml")

PathLike = Union[str, Path]


class ScenarioLoadError(ValueError):
    """A scenario file could not be read or failed validation."""

    def __init__(self, path: Path | None, message: str) -> None:
        self.path = path
        prefix = f"{path}: " if path is not None else ""
        super().__init__(f"{prefix}{message}")


def _format_validation_error(err: ValidationError) -> str:
    lines = []
    for item in err.errors():
        loc = ".".join(str(part) for part in item.get("loc", ())) or "<root>"
        lines.append(f"{loc}: {item.get('msg', 'invalid')}")
    return "; ".join(lines)


def parse_scenario(data: Any, *, path: Path | None = None) -> Scenario:
    """Validates a parsed YAML mapping as a :class:`Scenario`."""
    if not isinstance(data, dict):
        raise ScenarioLoadError(path, "a scenario file must contain a single mapping")
    try:
        return Scenario.model_validate(data)
    except ValidationError as err:
        raise ScenarioLoadError(path, _format_validation_error(err)) from None


def load_scenario(path: PathLike) -> Scenario:
    """Reads and validates one scenario file. Refuses on CI."""
    ensure_not_ci()
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise ScenarioLoadError(file_path, f"cannot read file ({err.strerror})") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise ScenarioLoadError(file_path, f"invalid YAML ({err})") from None
    return parse_scenario(data, path=file_path)


def iter_scenario_files(paths: Iterable[PathLike]) -> list[Path]:
    """Expands files and directories into a sorted, de-duplicated list of scenario files."""
    found: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for suffix in SCENARIO_SUFFIXES:
                found.update(f for f in p.rglob(f"*{suffix}") if f.is_file())
        elif p.is_file():
            if p.suffix not in SCENARIO_SUFFIXES:
                raise ScenarioLoadError(p, "not a .yaml or .yml file")
            found.add(p)
        else:
            raise ScenarioLoadError(p, "no such file or directory")
    return sorted(found)


def load_scenario_files(paths: Iterable[PathLike]) -> list[tuple[Path, Scenario]]:
    """Loads every scenario under ``paths`` with its file. Refuses on CI; rejects duplicate ids."""
    ensure_not_ci()
    loaded: list[tuple[Path, Scenario]] = []
    seen: dict[str, Path] = {}
    for file_path in iter_scenario_files(paths):
        scenario = load_scenario(file_path)
        if scenario.id in seen:
            raise ScenarioLoadError(
                file_path, f"duplicate scenario id {scenario.id!r} (also in {seen[scenario.id]})"
            )
        seen[scenario.id] = file_path
        loaded.append((file_path, scenario))
    return loaded


def load_scenarios(paths: Iterable[PathLike]) -> list[Scenario]:
    """Loads every scenario under ``paths``. Refuses on CI; rejects duplicate ids."""
    return [scenario for _path, scenario in load_scenario_files(paths)]
