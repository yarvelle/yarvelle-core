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

"""Tool and execution context schemas."""

from __future__ import annotations

from typing import Any, Callable, Dict, Literal, Optional
from pydantic import BaseModel, Field

ClosedToolName = Literal["attach-read", "workspace-note", "skill-docs"]


class ToolResult(BaseModel):
    success: bool
    output: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: Optional[bool] = None

    @property
    def code(self) -> Optional[str]:
        """Compatibility alias returning structured ``error_code``."""
        return self.error_code

    def to_jsonrpc_error(self) -> Optional[Dict[str, Any]]:
        """Maps a failed ``ToolResult`` into a deterministic MCP / JSON-RPC 2.0 error payload."""
        if self.success:
            return None
        from yarvelle_core.errors import YarvelleError, get_error_catalog

        resolved_code = self.error_code or "YRV-700-009"
        spec = get_error_catalog().get(resolved_code)
        if spec is not None:
            err = YarvelleError(spec, detail=self.error)
            payload = err.to_jsonrpc_error()
            if self.retryable is not None:
                payload["data"]["retryable"] = bool(self.retryable)
            return payload
        return {
            "code": -32603,
            "message": self.error or "Tool execution failed.",
            "data": {
                "yarvelle_code": resolved_code,
                "retryable": bool(self.retryable) if self.retryable is not None else False,
            },
        }


class ToolCallRecord(BaseModel):
    tool: str
    input: Dict[str, Any] = Field(default_factory=dict)
    allowed: bool = True
    duration_ms: float = 0.0
    success: bool = True
    output: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: Optional[bool] = None
