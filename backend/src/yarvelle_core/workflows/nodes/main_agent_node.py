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

"""Graph node that runs the main agent for model-routed turns.

The main agent hands work to registered agents through the Deep Agents
``task`` tool (see ``yarvelle_core.engine.orchestration``). If it fails and
the pack has a default agent, the turn is handed to that agent with a notice.

Subagent progress reaches the chat stream as ``task_status`` custom events and
degraded turns as ``orchestration_notice`` events; subagent tokens are never
streamed (see ``yarvelle_core.engine.service``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.config import settings
from yarvelle_core.constants.api import SSE_EVENT_ORCHESTRATION_NOTICE, SSE_EVENT_TASK_STATUS
from yarvelle_core.constants.paths import SKILLS_DIR
from yarvelle_core.engine.orchestration.reminder import MainAgentReminder
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID, HybridRouter, ToolResolver, TurnTaskSink
from yarvelle_core.engine.orchestration.task_guard import AuditSink, TaskStatusSink
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteSource
from yarvelle_core.schemas.tool_spec import RESERVED_TOOL_CONTEXT_PARAMS
from yarvelle_core.constants.agents import expand_workspace_note_tools
from yarvelle_core.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


def _json_schema_to_args_model(tool_name: str, parameters: Dict[str, Any]) -> type[BaseModel]:
    """Builds a Pydantic args_schema model from a ToolSpec JSON Schema object."""
    type_map: Dict[str, Any] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": List[Any],
        "object": Dict[str, Any],
    }
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    required_set = set(parameters.get("required") or []) if isinstance(parameters, dict) else set()
    fields: Dict[str, Any] = {}
    if isinstance(properties, dict):
        for prop_name, prop_schema in properties.items():
            if prop_name in RESERVED_TOOL_CONTEXT_PARAMS or not isinstance(prop_schema, dict):
                continue
            py_type = type_map.get(str(prop_schema.get("type", "string")), Any)
            desc = str(prop_schema.get("description") or "")
            if prop_name in required_set and "default" not in prop_schema:
                fields[prop_name] = (py_type, Field(..., description=desc))
            else:
                fields[prop_name] = (
                    Optional[py_type],
                    Field(default=prop_schema.get("default"), description=desc),
                )
    model_name = "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", tool_name) if part) or "Tool"
    return create_model(f"{model_name}Args", **fields)


async def _dispatch(name: str, payload: Dict[str, Any]) -> None:
    """Sends a custom stream event; a no-op outside a graph run."""
    try:
        from langchain_core.callbacks.manager import adispatch_custom_event

        await adispatch_custom_event(name, payload)
    except RuntimeError:
        pass  # no parent run (direct node call)


async def stream_task_status(payload: Dict[str, Any]) -> None:
    """Default ``status_sink``: forwards a task status to the chat stream."""
    await _dispatch(SSE_EVENT_TASK_STATUS, payload)


class MainAgentNode(BaseNode):
    """Runs the guarded main agent and returns its new messages."""

    def __init__(
        self,
        *,
        model: Optional[BaseChatModel],
        registry: AgentRegistry,
        orchestration: Optional[PackOrchestrationSpec] = None,
        default_agent: Optional[str] = None,
        audit_sink: Optional[AuditSink] = None,
        status_sink: Optional[TaskStatusSink] = None,
        tool_resolver: Optional[ToolResolver] = None,
        tool_registry: Optional[Any] = None,
        task_sink: Optional[TurnTaskSink] = None,
        name: str = "main_agent",
        reminder: Optional[MainAgentReminder] = None,
    ) -> None:
        super().__init__(name=name)
        self.tool_registry = tool_registry
        self.router = HybridRouter(
            registry=registry,
            model=model,
            spec=orchestration,
            default_agent=default_agent,
            audit_sink=audit_sink,
            status_sink=status_sink or stream_task_status,
            tool_resolver=tool_resolver,
            task_sink=task_sink,
            reminder=reminder,
        )

    def _build_turn_tool_resolver(self, state: Dict[str, Any]) -> ToolResolver:
        """Builds a per-turn governed ToolResolver wrapping ToolSpecs for subagent execution."""
        from yarvelle_core.engine.tool_exec import SqlApprovalStore, TaintFlag, ToolContext, execute_tool_call
        from yarvelle_core.engine.tool_registry import ToolSpec, create_default_registry

        ws_root = Path(state.get("workspace_root") or settings.workspace_root)
        skills_dir = Path(state.get("skills_dir") or (ws_root / SKILLS_DIR))
        user_id = str(state.get("user_id") or "default_user").strip() or "default_user"
        profile_id = str(state.get("profile_id") or "default_profile").strip() or "default_profile"
        run_id = str(state.get("thread_id") or state.get("turn_id") or "run-1")
        autonomy = str(state.get("autonomy") or "A1")
        is_tainted = bool(state.get("is_tainted"))
        default_reg = create_default_registry()
        app_store = SqlApprovalStore()

        def _resolve_for_subagent(agent_id: str, names: List[str]) -> List[Any]:
            expanded = expand_workspace_note_tools(list(names))
            agent_obj = self.router.registry.get(agent_id)
            ctx = ToolContext(
                user_id=user_id,
                profile_id=profile_id,
                run_id=run_id,
                autonomy=autonomy,  # type: ignore[arg-type]
                taint=TaintFlag(initial=is_tainted),
                workspace_root=ws_root,
                skills_dir=skills_dir,
                agent=agent_obj,
                effective_tools=tuple(expanded),
                skills=tuple(getattr(agent_obj, "skills", ()) if agent_obj else ()),
            )
            bound_tools: List[Any] = []
            for t_name in expanded:
                spec_obj = None
                if self.tool_registry is not None and hasattr(self.tool_registry, "get"):
                    candidate = self.tool_registry.get(t_name)
                    if isinstance(candidate, ToolSpec):
                        spec_obj = candidate
                if spec_obj is None:
                    spec_obj = default_reg.get(t_name)
                if not isinstance(spec_obj, ToolSpec):
                    continue
                args_model = _json_schema_to_args_model(spec_obj.name, spec_obj.parameters)

                def _make_tool(bound_spec: ToolSpec, bound_args_model: type[BaseModel]) -> StructuredTool:
                    async def _arun(**kwargs: Any) -> str:
                        clean_args = {k: v for k, v in kwargs.items() if v is not None}
                        res = await execute_tool_call(
                            ctx,
                            bound_spec,
                            clean_args,
                            approval_store=app_store,
                            agent_id=agent_id,
                        )
                        payload = res.output if res.success else {"error": res.error or "Tool execution failed."}
                        return payload if isinstance(payload, str) else json.dumps(payload, default=str)

                    def _run(**kwargs: Any) -> str:
                        return asyncio.run(_arun(**kwargs))

                    return StructuredTool.from_function(
                        func=_run,
                        coroutine=_arun,
                        name=bound_spec.name,
                        description=bound_spec.description or bound_spec.name,
                        args_schema=bound_args_model,
                    )

                bound_tools.append(_make_tool(spec_obj, args_model))
            return bound_tools

        return _resolve_for_subagent

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        active_resolver: Optional[ToolResolver] = None
        if self.router.tool_resolver is None and getattr(self.router.registry, "_tool_resolver", None) is None:
            active_resolver = self._build_turn_tool_resolver(state)
        outcome = await self.router.run(
            state,
            turn_id=state.get("turn_id"),
            thread_id=state.get("thread_id"),
            tool_resolver=active_resolver,
        )
        if outcome is None:
            return {"error": "No agent could take this turn.", "next_step": "error"}
        notices = [n.model_dump(mode="json") for n in outcome.notices]
        for notice in notices:
            await _dispatch(SSE_EVENT_ORCHESTRATION_NOTICE, notice)
        result: Dict[str, Any] = {
            "route_decision": outcome.decision.model_dump(mode="json", exclude_none=True),
        }
        if notices:
            result["orchestration_notices"] = list(state.get("orchestration_notices") or []) + notices
        if outcome.decision.source == RouteSource.MAIN_AGENT:
            # Which hand-offs fed this reply, by task id (built from the audit records).
            result["provenance"] = [p.model_dump(mode="json") for p in outcome.provenance]
            result.update(
                messages=outcome.messages,
                current_agent=MAIN_AGENT_ID,
                agent_id=MAIN_AGENT_ID,
                next_step="output_guardrail",
            )
            return result
        # Fallback: the chosen agent runs on the normal agent path.
        target = outcome.decision.agent_id or ""
        result.update(current_agent=target, routed_subgraph=target, agent_id=target, next_step="agent")
        return result


__all__ = ["MainAgentNode", "stream_task_status"]
