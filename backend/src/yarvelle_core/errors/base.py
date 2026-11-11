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

"""Typed YarvelleError exception base class and RFC 7807 / JSON-RPC mappers."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping, Optional, Union

from yarvelle_core.errors.catalog import (
    ErrorCatalog,
    ErrorCategory,
    ErrorCodeSpec,
    get_error_catalog,
)

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"

_SENSITIVE_CONTEXT_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "cookie",
    "credential",
    "kek",
    "dek",
)

REDACTED_VALUE = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(marker in lowered for marker in _SENSITIVE_CONTEXT_SUBSTRINGS)


def sanitize_error_context(raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Sanitizes structured context for safe serialization in HTTP and MCP responses."""
    if not raw:
        return {}

    def _clean(val: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[TRUNCATED]"
        if val is None or isinstance(val, (bool, int, float, str)):
            return val
        if isinstance(val, Mapping):
            out: Dict[str, Any] = {}
            for k, v in val.items():
                ks = str(k)
                out[ks] = REDACTED_VALUE if _is_sensitive_key(ks) else _clean(v, depth + 1)
            return out
        if isinstance(val, (list, tuple, set, frozenset)):
            return [_clean(item, depth + 1) for item in list(val)[:50]]
        return str(val)

    sanitized: Dict[str, Any] = {}
    for key, value in raw.items():
        key_str = str(key)
        if _is_sensitive_key(key_str):
            sanitized[key_str] = REDACTED_VALUE
        else:
            sanitized[key_str] = _clean(value)
    return sanitized


class YarvelleError(Exception):
    """Unified typed exception carrying an immutable ``YRV-XXX-YYY`` (or pack) error spec.

    Formatting of ``template`` is deferred lazily until ``.detail``, ``str(err)``,
    ``to_problem_details()``, or ``to_jsonrpc_error()`` is accessed.
    """

    DEFAULT_ERROR_CODE: str = "YRV-900-001"

    def __init__(
        self,
        code: Union[str, ErrorCodeSpec],
        *args: Any,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
        detail: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        instance: Optional[str] = None,
        catalog: Optional[ErrorCatalog] = None,
    ) -> None:
        if isinstance(code, ErrorCodeSpec):
            spec = code
        else:
            active_catalog = catalog or get_error_catalog()
            spec = active_catalog.resolve(code)

        self.spec: ErrorCodeSpec = spec
        self._format_args = tuple(args)
        self._raw_context: Dict[str, Any] = dict(context) if context is not None else {}
        self._detail_override: Optional[str] = detail
        self._formatted_detail: Optional[str] = None
        self._sanitized_context: Optional[Dict[str, Any]] = None
        self.headers: Optional[Dict[str, str]] = dict(headers) if headers else None
        self.instance: Optional[str] = instance

        # Pass only immutable code string to base Exception so lazy args are not evaluated eagerly.
        super().__init__(spec.code)
        if cause is not None:
            self.__cause__ = cause

    @property
    def code(self) -> str:
        return self.spec.code

    @property
    def slug(self) -> str:
        return self.spec.slug

    @property
    def category(self) -> ErrorCategory:
        return self.spec.category

    @property
    def http_status(self) -> int:
        return self.spec.http_status

    @property
    def status_code(self) -> int:
        """Compatibility alias matching HTTP exception conventions."""
        return self.spec.http_status

    @property
    def jsonrpc_code(self) -> int:
        return self.spec.jsonrpc_code

    @property
    def retryable(self) -> bool:
        return self.spec.retryable

    @property
    def title(self) -> str:
        return self.spec.title

    @property
    def context(self) -> Dict[str, Any]:
        if self._sanitized_context is None:
            self._sanitized_context = sanitize_error_context(self._raw_context)
        return dict(self._sanitized_context)

    @property
    def detail(self) -> str:
        if self._formatted_detail is None:
            if self._detail_override is not None:
                self._formatted_detail = str(self._detail_override)
            else:
                self._formatted_detail = self.spec.format_message(
                    self._format_args,
                    self._raw_context,
                )
        return self._formatted_detail

    def __str__(self) -> str:
        return self.detail

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(code={self.code!r}, slug={self.slug!r}, "
            f"http_status={self.http_status}, retryable={self.retryable})"
        )

    def to_problem_details(
        self,
        *,
        instance: Optional[str] = None,
        type_base_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Serializes this error as an RFC 7807 Problem Details dictionary."""
        payload: Dict[str, Any] = {
            "type": self.spec.type_uri(type_base_uri),
            "title": self.title,
            "status": self.http_status,
            "detail": self.detail,
            "code": self.code,
            "slug": self.slug,
            "retryable": self.retryable,
        }
        effective_instance = instance if instance is not None else self.instance
        if effective_instance is not None:
            payload["instance"] = effective_instance
        ctx = self.context
        if ctx:
            payload["context"] = ctx
        return payload

    def to_jsonrpc_error(self, *, include_context: bool = True) -> Dict[str, Any]:
        """Serializes this error as a deterministic MCP / JSON-RPC 2.0 error object."""
        data: Dict[str, Any] = {
            "yarvelle_code": self.code,
            "slug": self.slug,
            "category": self.category,
            "http_status": self.http_status,
            "retryable": self.retryable,
        }
        if include_context:
            ctx = self.context
            if ctx:
                data["context"] = ctx
        return {
            "code": self.jsonrpc_code,
            "message": self.detail,
            "data": data,
        }


def ensure_yarvelle_error(
    exc: BaseException,
    *,
    default_code: str = "YRV-900-001",
    context: Optional[Mapping[str, Any]] = None,
) -> YarvelleError:
    """Losslessly converts an arbitrary exception into a ``YarvelleError``.

    Already-typed ``YarvelleError`` instances pass through unchanged. Raw internal
    exception strings on unclassified ``500`` failures are never exposed in ``detail``.
    """
    if isinstance(exc, YarvelleError):
        return exc

    exc_type_name = type(exc).__name__
    merged_ctx: Dict[str, Any] = {"exception_type": exc_type_name}
    if context:
        merged_ctx.update(context)

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "Timeout" in exc_type_name:
        return YarvelleError(
            "YRV-600-006",
            context=merged_ctx,
            cause=exc,
        )
    if isinstance(exc, ConnectionError) or exc_type_name in ("NetworkError", "ConnectError", "RemoteProtocolError"):
        return YarvelleError(
            "YRV-600-007",
            context=merged_ctx,
            cause=exc,
        )
    if isinstance(exc, PermissionError):
        return YarvelleError(
            "YRV-300-004",
            context=merged_ctx,
            cause=exc,
            detail="Access denied.",
        )
    if isinstance(exc, FileNotFoundError):
        return YarvelleError(
            "YRV-500-001",
            context=merged_ctx,
            cause=exc,
            detail="Requested resource not found.",
        )
    return YarvelleError(
        default_code,
        context=merged_ctx,
        cause=exc,
        detail="An internal server error occurred." if default_code == "YRV-900-001" else None,
    )


__all__ = [
    "PROBLEM_JSON_MEDIA_TYPE",
    "REDACTED_VALUE",
    "YarvelleError",
    "ensure_yarvelle_error",
    "sanitize_error_context",
]
