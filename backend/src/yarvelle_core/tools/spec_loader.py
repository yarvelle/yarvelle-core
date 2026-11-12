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

"""Declarative YAML/JSON ToolSpecLoader and handler binding registry.

Loads, validates, and caches declarative ``yarvelle.tools/v1`` tool definitions from
``yarvelle_core/resources/tools/`` as well as pack-contributed tool manifests.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
import json
import logging
from pathlib import Path
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from pydantic import ValidationError
import yaml

from yarvelle_core.schemas.tool_spec import (
    API_VERSION_TOOLS_V1,
    DeclarativeToolSpec,
    HandlerToolBinding,
    KIND_TOOL_SET,
    ToolSetManifest,
)

logger = logging.getLogger("yarvelle_core.tools.spec_loader")

DEFAULT_CORE_TOOLS_DIR: Path = (
    Path(__file__).resolve().parents[1] / "resources" / "tools"
)


class ToolSpecValidationError(ValueError):
    """Raised when a declarative tool specification fails schema or handler validation."""


@dataclass(frozen=True)
class BoundDeclarativeTool:
    """Validated declarative tool specification paired with its resolved async executor."""

    spec: DeclarativeToolSpec
    executor: Optional[Callable[..., Any]]
    source_path: Path


def resolve_handler_entrypoint(entrypoint: str) -> Callable[..., Any]:
    """Resolves a ``module.path:function_name`` entrypoint to an async callable."""
    module_name, sep, attr_name = entrypoint.partition(":")
    if not sep or not module_name or not attr_name:
        raise ToolSpecValidationError(
            f"Invalid handler entrypoint '{entrypoint}': expected 'module.path:function_name'."
        )
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        raise ToolSpecValidationError(
            f"Failed to import handler module '{module_name}' for '{entrypoint}': {exc}"
        ) from exc

    fn = getattr(mod, attr_name, None)
    if fn is None or not callable(fn):
        raise ToolSpecValidationError(
            f"Handler '{attr_name}' in module '{module_name}' does not exist or is not callable."
        )
    if not inspect.iscoroutinefunction(fn):
        raise ToolSpecValidationError(
            f"Handler '{entrypoint}' must be an async coroutine function (`async def`)."
        )
    return fn


def _parse_manifest_file(path: Path, default_pack_id: str = "core") -> ToolSetManifest:
    """Parses a YAML or JSON declarative tool file into a validated ``ToolSetManifest``."""
    if not path.is_file():
        raise ToolSpecValidationError(f"Tool specification file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            raw_data = json.loads(raw_text)
        elif suffix in {".yaml", ".yml"}:
            raw_data = yaml.safe_load(raw_text)
        else:
            raise ToolSpecValidationError(
                f"Unsupported tool specification extension '{suffix}' in {path}; expected .yaml, .yml, or .json."
            )
    except ToolSpecValidationError:
        raise
    except Exception as exc:
        raise ToolSpecValidationError(f"Failed to parse {path}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ToolSpecValidationError(
            f"Declarative tool file {path} must deserialize to a mapping/object."
        )

    # Support single-tool Spector-style JSON/YAML objects in addition to ToolSet documents
    if "tools" not in raw_data and ("name" in raw_data or "id" in raw_data):
        raw_data = {
            "apiVersion": raw_data.get("apiVersion", API_VERSION_TOOLS_V1),
            "kind": KIND_TOOL_SET,
            "pack_id": raw_data.get("pack_id", default_pack_id),
            "tools": [
                {k: v for k, v in raw_data.items() if k not in {"apiVersion"}}
            ],
        }
    elif "pack_id" not in raw_data and default_pack_id != "core":
        raw_data = {**raw_data, "pack_id": default_pack_id}

    try:
        return ToolSetManifest.model_validate(raw_data)
    except ValidationError as exc:
        raise ToolSpecValidationError(
            f"Schema validation failed for {path}:\n{exc}"
        ) from exc


class ToolSpecLoader:
    """Thread-safe loader and cache for core and pack declarative tool specifications."""

    def __init__(self, core_tools_dir: Optional[Path] = None) -> None:
        self._core_tools_dir: Path = core_tools_dir or DEFAULT_CORE_TOOLS_DIR
        self._lock = threading.RLock()
        self._core_cache: Optional[Tuple[BoundDeclarativeTool, ...]] = None
        self._pack_sources: Dict[str, List[Path]] = {}
        self._pack_cache: Dict[str, Tuple[BoundDeclarativeTool, ...]] = {}

    @property
    def core_tools_dir(self) -> Path:
        return self._core_tools_dir

    def clear_cache(self) -> None:
        """Clears cached tool definitions (leaving registered pack source paths intact)."""
        with self._lock:
            self._core_cache = None
            self._pack_cache.clear()

    def register_pack_source(self, pack_id: str, path: Union[str, Path]) -> None:
        """Registers a YAML/JSON file or directory of declarative tool specs for ``pack_id``."""
        clean_pack = pack_id.strip().lower()
        if not clean_pack or clean_pack == "core":
            raise ValueError("Pack identifier for register_pack_source must be a non-'core' pack slug.")
        resolved = Path(path).resolve()
        with self._lock:
            existing = self._pack_sources.setdefault(clean_pack, [])
            if resolved not in existing:
                existing.append(resolved)
                self._pack_cache.pop(clean_pack, None)

    def unregister_pack_sources(self, pack_id: Optional[str] = None) -> None:
        """Removes registered pack tool sources (all packs if ``pack_id`` is None)."""
        with self._lock:
            if pack_id is None:
                self._pack_sources.clear()
                self._pack_cache.clear()
            else:
                clean_pack = pack_id.strip().lower()
                self._pack_sources.pop(clean_pack, None)
                self._pack_cache.pop(clean_pack, None)

    def registered_pack_ids(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._pack_sources.keys()))

    def load_file(
        self,
        path: Union[str, Path],
        *,
        default_pack_id: str = "core",
        resolve_handlers: bool = True,
    ) -> List[BoundDeclarativeTool]:
        """Loads and validates a single YAML or JSON tool specification file."""
        file_path = Path(path)
        manifest = _parse_manifest_file(file_path, default_pack_id=default_pack_id)
        bound: List[BoundDeclarativeTool] = []
        for spec in manifest.tools:
            executor: Optional[Callable[..., Any]] = None
            if resolve_handlers and isinstance(spec.binding, HandlerToolBinding):
                executor = resolve_handler_entrypoint(spec.binding.entrypoint)
            bound.append(
                BoundDeclarativeTool(
                    spec=spec,
                    executor=executor,
                    source_path=file_path,
                )
            )
        return bound

    def load_directory(
        self,
        directory: Union[str, Path],
        *,
        default_pack_id: str = "core",
        resolve_handlers: bool = True,
    ) -> List[BoundDeclarativeTool]:
        """Loads all ``*.yaml``, ``*.yml``, and ``*.json`` tool files in deterministic order."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise ToolSpecValidationError(f"Tool specification directory does not exist: {dir_path}")

        files = sorted(
            p
            for p in dir_path.iterdir()
            if p.is_file() and p.suffix.lower() in {".yaml", ".yml", ".json"}
        )
        seen_names: Dict[str, Path] = {}
        results: List[BoundDeclarativeTool] = []
        for file_path in files:
            for item in self.load_file(
                file_path,
                default_pack_id=default_pack_id,
                resolve_handlers=resolve_handlers,
            ):
                if item.spec.name in seen_names:
                    prev = seen_names[item.spec.name]
                    raise ToolSpecValidationError(
                        f"Duplicate tool name '{item.spec.name}' across {prev} and {file_path}."
                    )
                seen_names[item.spec.name] = file_path
                results.append(item)
        return results

    def load_core_tools(self) -> Tuple[BoundDeclarativeTool, ...]:
        """Loads and caches all built-in Yarvelle Core declarative tools."""
        with self._lock:
            if self._core_cache is None:
                loaded = self.load_directory(
                    self._core_tools_dir,
                    default_pack_id="core",
                    resolve_handlers=True,
                )
                self._core_cache = tuple(loaded)
            return self._core_cache

    def load_pack_tools(self, pack_id: str) -> Tuple[BoundDeclarativeTool, ...]:
        """Loads and caches declarative tools registered for ``pack_id``."""
        clean_pack = pack_id.strip().lower()
        with self._lock:
            if clean_pack in self._pack_cache:
                return self._pack_cache[clean_pack]
            paths = list(self._pack_sources.get(clean_pack, ()))
            if not paths:
                return ()

            seen: Dict[str, Path] = {}
            bound: List[BoundDeclarativeTool] = []
            for src in paths:
                items = (
                    self.load_directory(src, default_pack_id=clean_pack, resolve_handlers=True)
                    if src.is_dir()
                    else self.load_file(src, default_pack_id=clean_pack, resolve_handlers=True)
                )
                for item in items:
                    if item.spec.pack_id != clean_pack:
                        item = BoundDeclarativeTool(
                            spec=item.spec.model_copy(update={"pack_id": clean_pack}),
                            executor=item.executor,
                            source_path=item.source_path,
                        )
                    if item.spec.name in seen:
                        raise ToolSpecValidationError(
                            f"Duplicate pack tool '{item.spec.name}' in pack '{clean_pack}'."
                        )
                    seen[item.spec.name] = item.source_path
                    bound.append(item)
            cached = tuple(bound)
            self._pack_cache[clean_pack] = cached
            return cached

    def load_enabled_tools(
        self,
        enabled_packs: Optional[Sequence[str]] = None,
    ) -> Tuple[BoundDeclarativeTool, ...]:
        """Returns core tools plus tools belonging to ``enabled_packs``.

        When ``enabled_packs`` is None, all registered pack sources are included.
        When ``enabled_packs`` is an explicit sequence (e.g. ``[]`` or ``['finance']``),
        only ``core`` and the listed pack IDs are included.
        """
        core_items = list(self.load_core_tools())
        with self._lock:
            if enabled_packs is None:
                target_packs = sorted(self._pack_sources.keys())
            else:
                allowed = {p.strip().lower() for p in enabled_packs if p and p.strip()}
                target_packs = [p for p in sorted(self._pack_sources.keys()) if p in allowed]

        for pack_id in target_packs:
            core_items.extend(self.load_pack_tools(pack_id))
        return tuple(core_items)

    def get_closed_tool_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Returns OpenAI/LangChain tool definitions for Phase 0 closed sandbox tools."""
        definitions: Dict[str, Dict[str, Any]] = {}
        for item in self.load_core_tools():
            if item.spec.phase_0_closed:
                definitions[item.spec.name] = item.spec.to_tool_definition()
        return definitions

    def get_closed_tool_executors(self) -> Dict[str, Callable[..., Any]]:
        """Returns async executors for Phase 0 closed sandbox tools."""
        executors: Dict[str, Callable[..., Any]] = {}
        for item in self.load_core_tools():
            if item.spec.phase_0_closed and item.executor is not None:
                executors[item.spec.name] = item.executor
        return executors


_DEFAULT_TOOL_SPEC_LOADER = ToolSpecLoader()


def get_tool_spec_loader() -> ToolSpecLoader:
    """Returns the singleton ``ToolSpecLoader`` instance."""
    return _DEFAULT_TOOL_SPEC_LOADER


def register_pack_tool_manifest(pack_id: str, path: Union[str, Path]) -> None:
    """Registers a pack's declarative tool YAML/JSON file or directory with the default loader."""
    _DEFAULT_TOOL_SPEC_LOADER.register_pack_source(pack_id, path)


__all__ = [
    "BoundDeclarativeTool",
    "DEFAULT_CORE_TOOLS_DIR",
    "ToolSpecLoader",
    "ToolSpecValidationError",
    "get_tool_spec_loader",
    "register_pack_tool_manifest",
    "resolve_handler_entrypoint",
]
