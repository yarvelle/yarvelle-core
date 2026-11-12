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

"""Exception hierarchy for the connectors framework bridged onto YarvelleError."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from yarvelle_core.errors.base import YarvelleError


class ConnectorError(YarvelleError):
    """Base exception for all connector-related errors."""

    DEFAULT_ERROR_CODE = "YRV-600-001"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            code or self.DEFAULT_ERROR_CODE,
            context=context,
            cause=cause,
            detail=str(message) if message is not None else None,
        )


class EgressBlockedError(ConnectorError, PermissionError):
    """Raised when an outbound HTTP request targets a host, scheme, or port prohibited by policy."""

    DEFAULT_ERROR_CODE = "YRV-600-002"

    def __init__(
        self,
        message: str = "Outbound network egress blocked by security policy.",
        host: str | None = None,
        *,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        ctx: Dict[str, Any] = dict(context) if context else {}
        if host is not None:
            ctx.setdefault("host", host)
        super().__init__(message, code=self.DEFAULT_ERROR_CODE, context=ctx or None, cause=cause)
        self.host = host


class AuthExpiredError(ConnectorError):
    """Raised when connector authentication credentials have expired or require reauthorization."""

    DEFAULT_ERROR_CODE = "YRV-600-003"


class ManifestValidationError(ConnectorError, ValueError):
    """Raised when a connector manifest fails schema validation."""

    DEFAULT_ERROR_CODE = "YRV-200-002"


class ConnectorNotConfiguredError(ConnectorError):
    """Raised when a tool requires an external connector or MCP client that is not configured or attached."""


__all__ = [
    "AuthExpiredError",
    "ConnectorError",
    "ConnectorNotConfiguredError",
    "EgressBlockedError",
    "ManifestValidationError",
]
