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
from typing import Any, Dict, List, Mapping, Optional, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from yarvelle_core.agents.registry import AgentRegistry
from yarvelle_core.config import settings
from yarvelle_core.constants.api import (
    SSE_EVENT_ENTITY_CHANGED,
    SSE_EVENT_ORCHESTRATION_NOTICE,
    SSE_EVENT_TASK_STATUS,
)
from yarvelle_core.constants.paths import SKILLS_DIR
from yarvelle_core.engine.orchestration.reminder import MainAgentReminder
from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID, HybridRouter, ToolResolver, TurnTaskSink
from yarvelle_core.engine.orchestration.task_guard import AuditSink, TaskStatusSink
from yarvelle_core.schemas.events import build_entity_changed_payload
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteSource
from yarvelle_core.schemas.tool_spec import RESERVED_TOOL_CONTEXT_PARAMS
from yarvelle_core.scope.context import DEFAULT_SCOPE
from yarvelle_core.constants.agents import expand_workspace_note_tools
from yarvelle_core.workflows.nodes.base import BaseNode

logger = logging.getLogger(__name__)


_JSON_PRIMITIVE_TYPES: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": List[Any],
    "object": Dict[str, Any],
}


def _model_name_prefix(raw: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", raw) if part) or "Tool"


def _resolve_schema_node(
    node: Dict[str, Any],
    root_defs: Mapping[str, Any],
    *,
    seen_refs: Optional[set[str]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Resolves local $ref / anyOf / oneOf JSON Schema nodes into a concrete branch and nullable flag."""
    if not isinstance(node, dict):
        return {}, False
    resolved = dict(node)
    nullable = False
    visited = set(seen_refs or ())

    ref = resolved.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/") and ref not in visited:
        visited.add(ref)
        parts = ref[2:].split("/")
        target: Any = {"$defs": root_defs, "definitions": root_defs}
        for part in parts:
            target = target.get(part) if isinstance(target, Mapping) else None
        if isinstance(target, Mapping):
            merged = dict(target)
            for meta_key in ("description", "default", "title"):
                if meta_key in resolved and meta_key not in merged:
                    merged[meta_key] = resolved[meta_key]
            sub_node, sub_nullable = _resolve_schema_node(merged, root_defs, seen_refs=visited)
            return sub_node, nullable or sub_nullable

    for union_key in ("anyOf", "oneOf"):
        variants = resolved.get(union_key)
        if isinstance(variants, list):
            non_null: List[Dict[str, Any]] = []
            for opt in variants:
                if not isinstance(opt, dict):
                    continue
                if opt.get("type") == "null":
                    nullable = True
                    continue
                non_null.append(opt)
            if len(non_null) == 1:
                branch, branch_nullable = _resolve_schema_node(non_null[0], root_defs, seen_refs=visited)
                merged = dict(branch)
                for meta_key in ("description", "default", "title"):
                    if meta_key in resolved and not merged.get(meta_key):
                        merged[meta_key] = resolved[meta_key]
                return merged, nullable or branch_nullable
            if len(non_null) > 1:
                return resolved, nullable

    if resolved.get("type") == "null":
        nullable = True
    return resolved, nullable


def _schema_to_python_type(
    field_name: str,
    prop_schema: Dict[str, Any],
    root_defs: Mapping[str, Any],
    model_prefix: str,
) -> Tuple[Any, Dict[str, Any], bool]:
    """Converts a JSON Schema property node to a Python/Pydantic annotation plus resolved metadata."""
    resolved, is_nullable = _resolve_schema_node(prop_schema, root_defs)

    nested_props = resolved.get("properties")
    if isinstance(nested_props, dict) and nested_props:
        sub_prefix = f"{model_prefix}{_model_name_prefix(field_name)}"
        sub_model = _build_args_model_from_object(sub_prefix, resolved, root_defs, extra="allow")
        return sub_model, resolved, is_nullable

    schema_type = resolved.get("type")
    if schema_type == "array":
        items = resolved.get("items")
        if isinstance(items, dict):
            item_type, _, _ = _schema_to_python_type(f"{field_name}Item", items, root_defs, model_prefix)
            return List[item_type], resolved, is_nullable  # type: ignore[valid-type]
        return List[Any], resolved, is_nullable

    if isinstance(schema_type, str) and schema_type in _JSON_PRIMITIVE_TYPES:
        return _JSON_PRIMITIVE_TYPES[schema_type], resolved, is_nullable

    if "anyOf" in resolved or "oneOf" in resolved:
        return Any, resolved, is_nullable

    return str, resolved, is_nullable


def _build_args_model_from_object(
    model_prefix: str,
    schema_obj: Dict[str, Any],
    root_defs: Mapping[str, Any],
    *,
    extra: str = "ignore",
) -> type[BaseModel]:
    properties = schema_obj.get("properties") if isinstance(schema_obj, dict) else None
    required_set = set(schema_obj.get("required") or []) if isinstance(schema_obj, dict) else set()
    fields: Dict[str, Any] = {}
    if isinstance(properties, dict):
        for prop_name, raw_prop_schema in properties.items():
            if prop_name in RESERVED_TOOL_CONTEXT_PARAMS or not isinstance(raw_prop_schema, dict):
                continue
            py_type, resolved_prop, is_nullable = _schema_to_python_type(
                prop_name, raw_prop_schema, root_defs, model_prefix
            )
            desc = str(resolved_prop.get("description") or raw_prop_schema.get("description") or "")
            has_default = "default" in raw_prop_schema or "default" in resolved_prop
            default_val = raw_prop_schema.get("default", resolved_prop.get("default"))
            field_key = prop_name
            field_alias: Optional[str] = None
            if prop_name.startswith("_"):
                base_key = prop_name.lstrip("_") or "u"
                field_key = f"p_{base_key}"
                while field_key in fields:
                    field_key = f"{field_key}_"
                field_alias = prop_name
            field_kwargs: Dict[str, Any] = {"description": desc}
            if field_alias is not None:
                field_kwargs["alias"] = field_alias
            if prop_name in required_set and not has_default and not is_nullable:
                fields[field_key] = (py_type, Field(..., **field_kwargs))
            else:
                fields[field_key] = (
                    Optional[py_type],
                    Field(default=default_val, **field_kwargs),
                )
    return create_model(
        f"{model_prefix}Args",
        __config__=ConfigDict(extra=extra, populate_by_name=True),
        **fields,
    )


def _json_schema_to_args_model(tool_name: str, parameters: Dict[str, Any]) -> type[BaseModel]:
    """Builds a Pydantic args_schema model from a ToolSpec JSON Schema object."""
    root_defs: Dict[str, Any] = {}
    if isinstance(parameters, dict):
        for defs_key in ("$defs", "definitions"):
            block = parameters.get(defs_key)
            if isinstance(block, dict):
                root_defs.update(block)
    return _build_args_model_from_object(_model_name_prefix(tool_name), parameters or {}, root_defs)


def _to_plain_value(value: Any) -> Any:
    """Recursively converts nested Pydantic models into plain JSON-serializable dicts/lists."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True, by_alias=True)
    if isinstance(value, list):
        return [_to_plain_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_plain_value(v) for k, v in value.items()}
    return value


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
        enabled_packs = state.get("enabled_packs")
        default_reg = create_default_registry(enabled_packs=enabled_packs)
        app_store = SqlApprovalStore()

        def _resolve_for_subagent(agent_id: str, names: List[str]) -> List[Any]:
            agent_obj = self.router.registry.get(agent_id)
            effective_names = list(names)
            db_toolset_name = state.get("db_toolset") or getattr(agent_obj, "db_toolset", None)
            if db_toolset_name:
                try:
                    from yarvelle_core.tools.mcp_db_toolbox import get_db_toolbox

                    toolbox = get_db_toolbox()
                    if str(db_toolset_name) == "auto":
                        dom = str(getattr(agent_obj, "domain", "general") or "general")
                        rc = str(getattr(agent_obj, "risk_class", "assist") or "assist")
                        toolset_tools = toolbox.get_toolset_for_domain(dom, rc)
                    else:
                        toolset_tools = toolbox.get_toolset(str(db_toolset_name))
                    for t_name in toolset_tools:
                        if t_name not in effective_names:
                            effective_names.append(t_name)
                except Exception as err:
                    logger.debug("MCP DB toolset expansion skipped: %s", err)

            expanded = expand_workspace_note_tools(effective_names)
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
                        model_fields = bound_args_model.model_fields
                        clean_args = {
                            (
                                (model_fields[k].alias or k)
                                if k in model_fields
                                else k
                            ): _to_plain_value(v)
                            for k, v in kwargs.items()
                            if v is not None
                        }
                        res = await execute_tool_call(
                            ctx,
                            bound_spec,
                            clean_args,
                            approval_store=app_store,
                            agent_id=agent_id,
                        )
                        if (
                            res.success
                            and getattr(bound_spec, "risk_tier", "read") in ("write_local", "write_external", "irreversible")
                        ):
                            entity_payload = build_entity_changed_payload(
                                tool_name=bound_spec.name,
                                args=clean_args,
                                output=res.output,
                                profile_id=profile_id,
                                scope=str(getattr(ctx, "scope", DEFAULT_SCOPE)),
                            )
                            try:
                                from langchain_core.callbacks.manager import adispatch_custom_event

                                await adispatch_custom_event(SSE_EVENT_ENTITY_CHANGED, entity_payload)
                            except Exception as exc:
                                logger.debug("Failed to dispatch entity_changed event from subagent tool: %s", exc)

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
