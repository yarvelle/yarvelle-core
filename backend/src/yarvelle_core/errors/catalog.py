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

"""Immutable error code specification and extensible catalog loader.

Provides the foundation ``YRV-XXX-YYY`` taxonomy registry and disjoint pack
prefix registration without importing any higher runtime layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import string
import threading
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple, Union
import yaml

API_VERSION_ERRORS_V1 = "yarvelle.errors/v1"
DEFAULT_PROBLEM_TYPE_BASE_URI = "https://errors.yarvelle.dev"
RESERVED_CORE_ERROR_PREFIX = "YRV"

ErrorCategory = Literal[
    "validation",
    "configuration",
    "auth",
    "vault",
    "storage",
    "connector",
    "mcp_tools",
    "workflow",
    "internal",
]

BLOCK_TO_CATEGORY: Dict[int, ErrorCategory] = {
    100: "validation",
    200: "configuration",
    300: "auth",
    400: "vault",
    500: "storage",
    600: "connector",
    700: "mcp_tools",
    800: "workflow",
    900: "internal",
}

ERROR_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
ERROR_CODE_PATTERN = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]{1,5})-(?P<block>[1-9]00)-(?P<seq>\d{3})$")
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_FORMATTER = string.Formatter()


class ErrorCatalogRegistrationError(ValueError):
    """Raised when an error catalog entry or pack prefix violates taxonomy rules."""


@dataclass(frozen=True)
class ErrorCodeSpec:
    """Immutable specification of a single namespaced error code."""

    code: str
    slug: str
    category: ErrorCategory
    http_status: int
    jsonrpc_code: int
    retryable: bool
    title: str
    template: str
    description: str
    aliases: Tuple[str, ...] = ()
    pack_id: Optional[str] = None
    type_base_uri: str = DEFAULT_PROBLEM_TYPE_BASE_URI

    def __post_init__(self) -> None:
        match = ERROR_CODE_PATTERN.match(self.code)
        if not match:
            raise ErrorCatalogRegistrationError(
                f"Invalid error code '{self.code}': must match '<PREFIX>-<100..900>-<001..999>'."
            )
        seq = match.group("seq")
        if seq == "000":
            raise ErrorCatalogRegistrationError(
                f"Invalid error code '{self.code}': sequence '000' is reserved."
            )
        block = int(match.group("block"))
        expected_category = BLOCK_TO_CATEGORY.get(block)
        if expected_category is None or self.category != expected_category:
            raise ErrorCatalogRegistrationError(
                f"Error code '{self.code}' in block {block} must declare category "
                f"'{expected_category}', got '{self.category}'."
            )
        if not SLUG_PATTERN.match(self.slug):
            raise ErrorCatalogRegistrationError(
                f"Invalid error slug '{self.slug}' for code '{self.code}'."
            )
        if not isinstance(self.http_status, int) or isinstance(self.http_status, bool) or not (100 <= self.http_status <= 599):
            raise ErrorCatalogRegistrationError(
                f"Invalid http_status {self.http_status!r} for code '{self.code}'."
            )
        if not isinstance(self.jsonrpc_code, int) or isinstance(self.jsonrpc_code, bool) or self.jsonrpc_code > -32000:
            raise ErrorCatalogRegistrationError(
                f"Invalid jsonrpc_code {self.jsonrpc_code!r} for code '{self.code}': must be <= -32000."
            )
        if not isinstance(self.retryable, bool):
            raise ErrorCatalogRegistrationError(
                f"Field 'retryable' for code '{self.code}' must be a boolean."
            )
        if not self.title or not self.title.strip():
            raise ErrorCatalogRegistrationError(f"Field 'title' for code '{self.code}' must be non-empty.")
        if not self.template or not self.template.strip():
            raise ErrorCatalogRegistrationError(f"Field 'template' for code '{self.code}' must be non-empty.")
        if not self.description or not self.description.strip():
            raise ErrorCatalogRegistrationError(f"Field 'description' for code '{self.code}' must be non-empty.")

    @property
    def prefix(self) -> str:
        return self.code.split("-", 1)[0]

    @property
    def block(self) -> int:
        return int(self.code.split("-", 2)[1])

    def type_uri(self, base_uri: Optional[str] = None) -> str:
        root = (base_uri or self.type_base_uri or DEFAULT_PROBLEM_TYPE_BASE_URI).rstrip("/")
        return f"{root}/{self.code.lower()}"

    def format_message(
        self,
        args: Sequence[Any] = (),
        context: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Evaluates ``self.template`` against positional ``args`` and named ``context``."""
        ctx = dict(context or {})
        pieces: List[str] = []
        auto_idx = 0

        try:
            parsed = list(_FORMATTER.parse(self.template))
        except ValueError:
            return self.template

        for literal_text, field_name, format_spec, conversion in parsed:
            pieces.append(literal_text)
            if field_name is None:
                continue

            resolved: Any
            found = False
            if field_name == "":
                if auto_idx < len(args):
                    resolved = args[auto_idx]
                    found = True
                auto_idx += 1
            elif field_name.isdigit():
                idx = int(field_name)
                if idx < len(args):
                    resolved = args[idx]
                    found = True
            else:
                if field_name in ctx and ctx[field_name] is not None:
                    resolved = ctx[field_name]
                    found = True
                elif auto_idx < len(args):
                    resolved = args[auto_idx]
                    auto_idx += 1
                    found = True

            if not found:
                resolved = ""
            else:
                if conversion == "r":
                    resolved = repr(resolved)
                elif conversion == "s":
                    resolved = str(resolved)
                elif conversion == "a":
                    resolved = ascii(resolved)
                if format_spec:
                    try:
                        resolved = format(resolved, format_spec)
                    except Exception:
                        resolved = str(resolved)
                else:
                    resolved = str(resolved)
            pieces.append(resolved)

        rendered = "".join(pieces).strip()
        if rendered.endswith(":"):
            rendered = rendered[:-1].rstrip()
            if rendered and not rendered.endswith("."):
                rendered = f"{rendered}."
        return rendered or self.title


def _spec_from_raw(
    slug: str,
    raw: Mapping[str, Any],
    *,
    pack_id: Optional[str] = None,
    default_type_base_uri: str = DEFAULT_PROBLEM_TYPE_BASE_URI,
) -> ErrorCodeSpec:
    code = str(raw.get("code") or "").strip()
    category = raw.get("category")
    http_status = raw.get("http_status", raw.get("status_code"))
    jsonrpc_code = raw.get("jsonrpc_code")
    retryable = raw.get("retryable")
    title = str(raw.get("title") or "").strip()
    template = str(raw.get("template") or raw.get("message") or "").strip()
    description = str(raw.get("description") or "").strip()
    raw_aliases = raw.get("aliases") or ()
    aliases = tuple(str(a).strip() for a in raw_aliases if str(a).strip())
    type_base = str(raw.get("type_base_uri") or default_type_base_uri).strip()
    return ErrorCodeSpec(
        code=code,
        slug=slug,
        category=category,  # type: ignore[arg-type]
        http_status=http_status,  # type: ignore[arg-type]
        jsonrpc_code=jsonrpc_code,  # type: ignore[arg-type]
        retryable=retryable,  # type: ignore[arg-type]
        title=title,
        template=template,
        description=description,
        aliases=aliases,
        pack_id=pack_id,
        type_base_uri=type_base,
    )


class ErrorCatalog:
    """Thread-safe immutable core + extensible pack error code registry."""

    def __init__(self, core_yaml_path: Optional[Path] = None) -> None:
        self._core_yaml_path = (
            core_yaml_path
            or (Path(__file__).resolve().parent.parent / "resources" / "errors.yaml")
        ).resolve()
        self._lock = threading.RLock()
        self._by_code: Dict[str, ErrorCodeSpec] = {}
        self._by_slug: Dict[str, ErrorCodeSpec] = {}
        self._pack_prefixes: Dict[str, str] = {}
        self._prefix_owners: Dict[str, str] = {RESERVED_CORE_ERROR_PREFIX: "core"}
        self._loaded_core = False

    def _ensure_loaded(self) -> None:
        if self._loaded_core:
            return
        with self._lock:
            if self._loaded_core:
                return
            with open(self._core_yaml_path, "r", encoding="utf-8") as fh:
                payload = yaml.safe_load(fh) or {}
            base_uri = str(payload.get("type_base_uri") or DEFAULT_PROBLEM_TYPE_BASE_URI)
            raw_errors = payload.get("errors") or {}
            if not isinstance(raw_errors, Mapping) or not raw_errors:
                raise ErrorCatalogRegistrationError(
                    f"Core error catalog '{self._core_yaml_path}' must define a non-empty 'errors' mapping."
                )
            for slug, entry in raw_errors.items():
                if not isinstance(entry, Mapping):
                    raise ErrorCatalogRegistrationError(
                        f"Core error entry '{slug}' must be a mapping."
                    )
                spec = _spec_from_raw(str(slug), entry, pack_id=None, default_type_base_uri=base_uri)
                if spec.prefix != RESERVED_CORE_ERROR_PREFIX:
                    raise ErrorCatalogRegistrationError(
                        f"Core error '{spec.code}' must use reserved '{RESERVED_CORE_ERROR_PREFIX}' prefix."
                    )
                self._insert_locked(spec)
            self._loaded_core = True

    def _insert_locked(self, spec: ErrorCodeSpec) -> None:
        if spec.code in self._by_code:
            existing = self._by_code[spec.code]
            raise ErrorCatalogRegistrationError(
                f"Duplicate error code '{spec.code}' (already registered by slug '{existing.slug}')."
            )
        if spec.slug in self._by_slug:
            existing = self._by_slug[spec.slug]
            raise ErrorCatalogRegistrationError(
                f"Duplicate error slug '{spec.slug}' (already registered to code '{existing.code}')."
            )
        for alias in spec.aliases:
            if not SLUG_PATTERN.match(alias):
                raise ErrorCatalogRegistrationError(
                    f"Invalid alias '{alias}' on code '{spec.code}'."
                )
            if alias in self._by_slug:
                existing = self._by_slug[alias]
                raise ErrorCatalogRegistrationError(
                    f"Duplicate error alias '{alias}' (collides with code '{existing.code}')."
                )
        self._by_code[spec.code] = spec
        self._by_slug[spec.slug] = spec
        for alias in spec.aliases:
            self._by_slug[alias] = spec

    def resolve(self, code_or_slug: str) -> ErrorCodeSpec:
        """Resolves either a canonical code (``YRV-300-001``) or slug (``authentication_required``)."""
        self._ensure_loaded()
        key = (code_or_slug or "").strip()
        with self._lock:
            spec = self._by_code.get(key) or self._by_slug.get(key)
        if spec is None:
            raise KeyError(f"Unknown error code or slug: {code_or_slug!r}")
        return spec

    def get(self, code_or_slug: str) -> Optional[ErrorCodeSpec]:
        """Returns ``ErrorCodeSpec`` if registered, otherwise ``None``."""
        try:
            return self.resolve(code_or_slug)
        except KeyError:
            return None

    def list_specs(self, *, pack_id: Optional[str] = "__all__") -> List[ErrorCodeSpec]:
        """Returns registered specs sorted by error code."""
        self._ensure_loaded()
        with self._lock:
            specs = list(self._by_code.values())
        if pack_id != "__all__":
            specs = [s for s in specs if s.pack_id == pack_id]
        return sorted(specs, key=lambda s: s.code)

    def register_pack_catalog(
        self,
        pack_id: str,
        prefix: str,
        entries_or_source: Union[
            Path,
            str,
            Mapping[str, Any],
            Sequence[Union[ErrorCodeSpec, Mapping[str, Any]]],
        ],
        *,
        type_base_uri: str = DEFAULT_PROBLEM_TYPE_BASE_URI,
    ) -> List[ErrorCodeSpec]:
        """Registers a disjoint ``<PREFIX>-XXX-YYY`` error catalog owned by ``pack_id``."""
        self._ensure_loaded()
        clean_pack = (pack_id or "").strip().lower()
        if not clean_pack or clean_pack == "core":
            raise ErrorCatalogRegistrationError("pack_id must be a non-empty pack slug other than 'core'.")

        clean_prefix = (prefix or "").strip().upper()
        if not ERROR_PREFIX_PATTERN.match(clean_prefix):
            raise ErrorCatalogRegistrationError(
                f"Invalid pack error prefix '{prefix}': must match {ERROR_PREFIX_PATTERN.pattern}."
            )
        if clean_prefix == RESERVED_CORE_ERROR_PREFIX:
            raise ErrorCatalogRegistrationError(
                f"Error prefix '{RESERVED_CORE_ERROR_PREFIX}' is reserved exclusively for yarvelle-core."
            )

        parsed_specs = self._parse_pack_entries(
            clean_pack,
            clean_prefix,
            entries_or_source,
            default_type_base_uri=type_base_uri,
        )

        with self._lock:
            owner = self._prefix_owners.get(clean_prefix)
            if owner is not None and owner != clean_pack:
                raise ErrorCatalogRegistrationError(
                    f"Error prefix '{clean_prefix}' is already registered to pack '{owner}'."
                )
            existing_prefix = self._pack_prefixes.get(clean_pack)
            if existing_prefix is not None and existing_prefix != clean_prefix:
                raise ErrorCatalogRegistrationError(
                    f"Pack '{clean_pack}' already registered prefix '{existing_prefix}' (cannot also claim '{clean_prefix}')."
                )

            # Validate atomically before mutating state so partial failures leave catalog clean.
            seen_codes = set()
            seen_slugs = set()
            to_insert: List[ErrorCodeSpec] = []
            for spec in parsed_specs:
                existing_by_code = self._by_code.get(spec.code)
                if existing_by_code is not None:
                    if existing_by_code == spec:
                        continue
                    raise ErrorCatalogRegistrationError(
                        f"Duplicate error code '{spec.code}' conflicts with '{existing_by_code.slug}'."
                    )
                if spec.code in seen_codes:
                    raise ErrorCatalogRegistrationError(f"Duplicate error code '{spec.code}' within pack '{clean_pack}'.")
                if spec.slug in self._by_slug or spec.slug in seen_slugs:
                    raise ErrorCatalogRegistrationError(f"Duplicate error slug '{spec.slug}' in pack '{clean_pack}'.")
                for alias in spec.aliases:
                    if alias in self._by_slug or alias in seen_slugs:
                        raise ErrorCatalogRegistrationError(
                            f"Duplicate error alias '{alias}' in pack '{clean_pack}'."
                        )
                    seen_slugs.add(alias)
                seen_codes.add(spec.code)
                seen_slugs.add(spec.slug)
                to_insert.append(spec)

            self._prefix_owners[clean_prefix] = clean_pack
            self._pack_prefixes[clean_pack] = clean_prefix
            for spec in to_insert:
                self._insert_locked(spec)

        return parsed_specs

    def unregister_pack_catalog(self, pack_id: str) -> None:
        """Removes all error codes registered by ``pack_id`` (intended for test isolation)."""
        clean_pack = (pack_id or "").strip().lower()
        with self._lock:
            prefix = self._pack_prefixes.pop(clean_pack, None)
            if prefix is not None and self._prefix_owners.get(prefix) == clean_pack:
                self._prefix_owners.pop(prefix, None)
            codes_to_drop = [c for c, spec in self._by_code.items() if spec.pack_id == clean_pack]
            for code in codes_to_drop:
                spec = self._by_code.pop(code)
                if self._by_slug.get(spec.slug) == spec:
                    self._by_slug.pop(spec.slug, None)
                for alias in spec.aliases:
                    if self._by_slug.get(alias) == spec:
                        self._by_slug.pop(alias, None)

    @staticmethod
    def _parse_pack_entries(
        pack_id: str,
        prefix: str,
        entries_or_source: Union[
            Path,
            str,
            Mapping[str, Any],
            Sequence[Union[ErrorCodeSpec, Mapping[str, Any]]],
        ],
        *,
        default_type_base_uri: str,
    ) -> List[ErrorCodeSpec]:
        source: Any = entries_or_source
        if isinstance(entries_or_source, (Path, str)):
            path = Path(entries_or_source)
            with open(path, "r", encoding="utf-8") as fh:
                source = yaml.safe_load(fh) or {}

        effective_base = default_type_base_uri
        raw_items: Iterable[Tuple[str, Union[ErrorCodeSpec, Mapping[str, Any]]]]
        if isinstance(source, Mapping):
            if "type_base_uri" in source and source["type_base_uri"]:
                effective_base = str(source["type_base_uri"]).strip()
            declared_prefix = source.get("prefix")
            if declared_prefix and str(declared_prefix).strip().upper() != prefix:
                raise ErrorCatalogRegistrationError(
                    f"Catalog file declares prefix '{declared_prefix}', expected '{prefix}'."
                )
            inner = source.get("errors", source)
            if isinstance(inner, Mapping):
                raw_items = [(str(k), v) for k, v in inner.items()]
            elif isinstance(inner, Sequence):
                raw_items = [(str(item.get("slug") or ""), item) for item in inner if isinstance(item, Mapping)]
            else:
                raise ErrorCatalogRegistrationError("Pack error catalog 'errors' must be a mapping or list.")
        elif isinstance(source, Sequence):
            items_list: List[Tuple[str, Union[ErrorCodeSpec, Mapping[str, Any]]]] = []
            for item in source:
                if isinstance(item, ErrorCodeSpec):
                    items_list.append((item.slug, item))
                elif isinstance(item, Mapping):
                    items_list.append((str(item.get("slug") or ""), item))
                else:
                    raise ErrorCatalogRegistrationError(f"Unsupported pack error entry: {item!r}")
            raw_items = items_list
        else:
            raise ErrorCatalogRegistrationError("Unsupported pack error catalog source.")

        specs: List[ErrorCodeSpec] = []
        for slug, item in raw_items:
            if isinstance(item, ErrorCodeSpec):
                spec = ErrorCodeSpec(
                    code=item.code,
                    slug=item.slug,
                    category=item.category,
                    http_status=item.http_status,
                    jsonrpc_code=item.jsonrpc_code,
                    retryable=item.retryable,
                    title=item.title,
                    template=item.template,
                    description=item.description,
                    aliases=item.aliases,
                    pack_id=pack_id,
                    type_base_uri=item.type_base_uri or effective_base,
                )
            else:
                eff_slug = str(item.get("slug") or slug).strip()
                spec = _spec_from_raw(
                    eff_slug,
                    item,
                    pack_id=pack_id,
                    default_type_base_uri=effective_base,
                )
            if spec.prefix != prefix:
                raise ErrorCatalogRegistrationError(
                    f"Pack '{pack_id}' error code '{spec.code}' must start with registered prefix '{prefix}-'."
                )
            specs.append(spec)
        return specs


_CATALOG_LOCK = threading.Lock()
_DEFAULT_CATALOG: Optional[ErrorCatalog] = None


def get_error_catalog() -> ErrorCatalog:
    """Returns the process-wide thread-safe ``ErrorCatalog`` singleton."""
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        with _CATALOG_LOCK:
            if _DEFAULT_CATALOG is None:
                _DEFAULT_CATALOG = ErrorCatalog()
    return _DEFAULT_CATALOG


def register_pack_error_catalog(
    pack_id: str,
    prefix: str,
    entries_or_source: Union[
        Path,
        str,
        Mapping[str, Any],
        Sequence[Union[ErrorCodeSpec, Mapping[str, Any]]],
    ],
    *,
    type_base_uri: str = DEFAULT_PROBLEM_TYPE_BASE_URI,
) -> List[ErrorCodeSpec]:
    """Registers a downstream pack's ``<PREFIX>-XXX-YYY`` catalog entries."""
    return get_error_catalog().register_pack_catalog(
        pack_id,
        prefix,
        entries_or_source,
        type_base_uri=type_base_uri,
    )


def unregister_pack_error_catalog(pack_id: str) -> None:
    """Unregisters a downstream pack's error catalog entries."""
    get_error_catalog().unregister_pack_catalog(pack_id)


__all__ = [
    "API_VERSION_ERRORS_V1",
    "BLOCK_TO_CATEGORY",
    "DEFAULT_PROBLEM_TYPE_BASE_URI",
    "ERROR_CODE_PATTERN",
    "ERROR_PREFIX_PATTERN",
    "RESERVED_CORE_ERROR_PREFIX",
    "ErrorCatalog",
    "ErrorCatalogRegistrationError",
    "ErrorCategory",
    "ErrorCodeSpec",
    "get_error_catalog",
    "register_pack_error_catalog",
    "unregister_pack_error_catalog",
]
