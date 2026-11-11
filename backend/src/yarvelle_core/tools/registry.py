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

"""Phase 0 closed sandbox tool registry backed by the canonical declarative ToolSpecLoader."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Optional

from yarvelle_core.schemas.tool import CLOSED_TOOL_NAMES, ToolResult
from yarvelle_core.tools.spec_loader import get_tool_spec_loader


def _build_closed_tool_definitions() -> Dict[str, Dict[str, Any]]:
    raw = get_tool_spec_loader().get_closed_tool_definitions()
    ordered: Dict[str, Dict[str, Any]] = {}
    for name in CLOSED_TOOL_NAMES:
        if name in raw:
            ordered[name] = raw[name]
    for name, definition in raw.items():
        if name not in ordered:
            ordered[name] = definition
    return ordered


CLOSED_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = _build_closed_tool_definitions()

TOOL_EXECUTORS: Dict[str, Callable[[Dict[str, Any], Any], Coroutine[Any, Any, ToolResult]]] = (
    get_tool_spec_loader().get_closed_tool_executors()
)


def get_closed_tool(name: str) -> Optional[Dict[str, Any]]:
    """Returns the closed tool definition from the canonical declarative catalog."""
    return get_tool_spec_loader().get_closed_tool_definitions().get(name)


def get_all_tool_definitions() -> List[Dict[str, Any]]:
    """Returns all Phase 0 closed tool definitions from the canonical declarative catalog."""
    return list(_build_closed_tool_definitions().values())


async def execute_tool(name: str, params: Dict[str, Any], context: Any) -> ToolResult:
    """Dispatches and executes a Phase 0 closed sandbox tool safely."""
    executor = TOOL_EXECUTORS.get(name) or get_tool_spec_loader().get_closed_tool_executors().get(name)
    if not executor:
        return ToolResult(
            success=False,
            output=None,
            error=f'Tool "{name}" is not recognized or not available in the Phase 0 closed tool registry.',
        )

    try:
        return await executor(params, context)
    except Exception as err:
        return ToolResult(
            success=False,
            output=None,
            error=f"Tool execution failed: {err}",
        )


__all__ = [
    "CLOSED_TOOL_DEFINITIONS",
    "TOOL_EXECUTORS",
    "execute_tool",
    "get_all_tool_definitions",
    "get_closed_tool",
]
