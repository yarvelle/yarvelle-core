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

"""Secure pack-native resource path resolution.

Resolves relative resource paths under a pack root with root containment,
extension allowlisting, size limits, and symlink-escape refusal. This lets
packs ship YAML/MD resource and workflow pattern files without relying on
application-side import-time injection into core's ResourceLoader.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Dict, FrozenSet, Iterable, Optional, Set, Union

import yaml

ALLOWED_RESOURCE_EXTENSIONS: FrozenSet[str] = frozenset({".yaml", ".yml", ".json", ".md", ".txt"})
DEFAULT_MAX_RESOURCE_BYTES: int = 1_048_576  # 1 MiB
DEFAULT_ALLOWED_PREFIXES: FrozenSet[str] = frozenset({"resources", "workflows", "agents", "skills", "schemas", "connectors"})


class PackResourceError(PermissionError):
    """Raised when a pack resource path fails security or validation checks."""


def _normalize_prefix(raw: str) -> str:
    text = (raw or "").strip().replace("\\", "/")
    text = text.lstrip("./")
    return text.strip("/")


class PackResourceResolver:
    """Resolve and read files under a single pack root with containment checks."""

    def __init__(
        self,
        pack_id: str,
        pack_root: Union[Path, str],
        *,
        allowed_prefixes: Optional[Iterable[str]] = None,
        max_bytes: int = DEFAULT_MAX_RESOURCE_BYTES,
        allowed_extensions: Optional[Iterable[str]] = None,
    ) -> None:
        if not pack_id or not str(pack_id).strip():
            raise ValueError("pack_id is required")
        root = Path(pack_root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Pack root does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Pack root is not a directory: {root}")
        self.pack_id = str(pack_id).strip()
        self.pack_root = root
        prefixes: Set[str] = set(DEFAULT_ALLOWED_PREFIXES)
        if allowed_prefixes:
            for item in allowed_prefixes:
                norm = _normalize_prefix(item)
                if norm:
                    prefixes.add(norm.split("/", 1)[0])
        self.allowed_prefixes: FrozenSet[str] = frozenset(prefixes)
        self.max_bytes = int(max_bytes)
        exts = set(ALLOWED_RESOURCE_EXTENSIONS)
        if allowed_extensions:
            for ext in allowed_extensions:
                e = ext if str(ext).startswith(".") else f".{ext}"
                exts.add(e.lower())
        self.allowed_extensions: FrozenSet[str] = frozenset(exts)

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve ``relative_path`` under the pack root or raise PackResourceError."""
        if relative_path is None:
            raise PackResourceError("Resource path is required")
        raw = str(relative_path)
        if raw == "" or raw.strip() == "":
            raise PackResourceError("Resource path is empty")
        if "\x00" in raw:
            raise PackResourceError("Resource path contains a null byte")
        if "://" in raw:
            raise PackResourceError(f"URI schemes are not allowed in resource paths: {raw!r}")
        candidate = PurePosixPath(raw.replace("\\", "/"))
        if candidate.is_absolute() or raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
            raise PackResourceError(f"Absolute resource paths are not allowed: {raw!r}")
        if ".." in candidate.parts:
            raise PackResourceError(f"Path traversal is not allowed: {raw!r}")
        if not candidate.parts:
            raise PackResourceError(f"Resource path is empty: {raw!r}")
        top = candidate.parts[0]
        if top not in self.allowed_prefixes:
            raise PackResourceError(
                f"Path '{raw}' is outside allowed pack subtrees {sorted(self.allowed_prefixes)}"
            )
        ext = Path(candidate.name).suffix.lower()
        if ext not in self.allowed_extensions:
            raise PackResourceError(
                f"Extension '{ext or '<none>'}' is not allowed for pack resources "
                f"(allowed: {sorted(self.allowed_extensions)})"
            )

        # Walk each ancestor and refuse symlink escape before opening the target.
        current = self.pack_root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                target = current.resolve()
                if not target.is_relative_to(self.pack_root):
                    raise PackResourceError(
                        f"Symlink escape refused for '{raw}' -> '{target}' outside pack root"
                    )

        resolved = (self.pack_root / Path(*candidate.parts)).resolve()
        if not resolved.is_relative_to(self.pack_root):
            raise PackResourceError(
                f"Resolved path '{resolved}' escapes pack root '{self.pack_root}'"
            )
        return resolved

    def read_bytes(self, relative_path: str) -> bytes:
        path = self.resolve_path(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Pack resource not found: {relative_path} (pack={self.pack_id})")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise PackResourceError(
                f"Pack resource '{relative_path}' exceeds max size {self.max_bytes} bytes (got {size})"
            )
        return path.read_bytes()

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(relative_path).decode(encoding)

    def load_yaml(self, relative_path: str) -> Dict[str, Any]:
        data = yaml.safe_load(self.read_text(relative_path)) or {}
        if not isinstance(data, dict):
            raise PackResourceError(f"Pack YAML '{relative_path}' must be a mapping")
        return data

    def load_json(self, relative_path: str) -> Dict[str, Any]:
        data = json.loads(self.read_text(relative_path))
        if not isinstance(data, dict):
            raise PackResourceError(f"Pack JSON '{relative_path}' must be a mapping")
        return data


def prefixes_for_pack(provides: Any = None, routing_hints: Any = None) -> Set[str]:
    """Collect allowed top-level prefixes from PackProvidesSpec / RoutingHints."""
    prefixes: Set[str] = set(DEFAULT_ALLOWED_PREFIXES)
    if provides is not None:
        for attr in (
            "agents_dir",
            "skills_dir",
            "prompts_dir",
            "locales_dir",
            "connectors_dir",
            "resources_dir",
            "workflows_dir",
            "evals",
        ):
            value = getattr(provides, attr, None)
            if isinstance(value, str) and value.strip():
                top = _normalize_prefix(value).split("/", 1)[0]
                if top:
                    prefixes.add(top)
    if routing_hints is not None:
        patterns = getattr(routing_hints, "patterns_resource", None)
        if isinstance(patterns, str) and patterns.strip():
            top = _normalize_prefix(patterns).split("/", 1)[0]
            if top:
                prefixes.add(top)
    return prefixes


def resolve_pack_root(pack: Any) -> Optional[Path]:
    """Best-effort filesystem root for a PackSpec (manifest parent when present)."""
    manifest_path = getattr(pack, "manifest_path", None)
    if isinstance(manifest_path, str) and manifest_path.strip():
        path = Path(manifest_path).expanduser()
        if path.is_file():
            return path.parent.resolve()
        if path.is_dir():
            return path.resolve()
    pack_root = getattr(pack, "pack_root", None)
    if pack_root:
        return Path(pack_root).resolve()
    return None
