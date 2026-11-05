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

"""OrchestratorNode: the routing step at the top of the agent graph.

Order: an explicit agent choice, then pack fixed routes (no model call), then
the main agent when it is wired in. Without a model the pack default agent
takes the turn with a ``model_unavailable`` notice. Routing never guesses from
prompt keywords and never substitutes an unknown agent silently.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from yarvelle_core.agents.registry import AgentRegistry, _extract_first_line
from yarvelle_core.config import settings
from yarvelle_core.engine.orchestration.routing import (
    BUILTIN_DOCUMENT_ROUTE_ID,
    has_attachments,
    select_fixed_route,
)
from yarvelle_core.engine.orchestration.runtime import (
    MAIN_AGENT_ID,
    pick_rejection,
    record_rejected_pick,
    record_route,
)
from yarvelle_core.engine.orchestration.task_guard import AuditSink
from yarvelle_core.constants.agents import AGENT_DOCUMENT_EXTRACTOR, AGENT_ORCHESTRATOR
from yarvelle_core.constants.paths import AGENTS_DIR, SKILLS_DIR
from yarvelle_core.memory.ports.catalog_port import CatalogPort
from yarvelle_core.resources.loader import get_resource_loader
from yarvelle_core.schemas.manifest import AgentManifest
from yarvelle_core.schemas.plan import (
    AgentTask,
    DeliberationConfig,
    ExecutionMode,
    ExecutionPlan,
)
from yarvelle_core.schemas.orchestration import PackOrchestrationSpec, RouteDecision, RouteSource
from yarvelle_core.schemas.routing import RoutingHints
from yarvelle_core.templates.engine import render_template
from yarvelle_core.workflows.nodes.base import BaseNode
from yarvelle_core.workflows.state import AgentState, extract_text_content

logger = logging.getLogger(__name__)


class DomainClassification(BaseModel):
    """Structured classification output for Tier-1 domain routing."""

    domain: str = Field(
        ...,
        description="Primary domain classification identifier.",
    )
    category: str = Field(
        default="",
        description="Dot-notated subcategory path (e.g. 'general.support', 'analytics.metrics').",
    )
    reasoning: str = Field(
        default="",
        description="Brief classification rationale.",
    )


DEFAULT_ROUTING_HINTS = [
    RoutingHints(
        domain="general",
        description="General assistance, inquiry routing, and cross-domain stewardship.",
        default_agent="general-steward",
        domains_info={
            "example_categories": "general.support, operations.tasks, workspace.notes",
        },
    ),
    RoutingHints(
        domain="analytics",
        description="Data analysis, metrics calculation, reporting, structured evaluation, and quantitative synthesis.",
        default_agent="analytics-guide",
        domains_info={
            "example_categories": "analytics.metrics, analytics.reporting, analytics.summary",
        },
    ),
    RoutingHints(
        domain="documents",
        description="Document extraction, structured record processing, document dossiers, and text analysis.",
        default_agent="document-extractor",
        domains_info={
            "example_categories": "documents.extraction, documents.records, documents.verification",
        },
    ),
]


def compose_tier1_classifier_prompt(
    hints: Optional[Sequence[RoutingHints]] = None,
    product_name: str = "Yarvelle Core",
) -> str:
    """Composes the Tier-1 Domain Classifier prompt dynamically from RoutingHints."""
    active_hints = list(hints) if hints is not None else DEFAULT_ROUTING_HINTS
    domains = [h.domain for h in active_hints]
    domains_quoted = ", ".join(f"'{d}'" for d in domains)

    domain_blocks = []
    for idx, h in enumerate(active_hints, 1):
        example_cats = h.domains_info.get("example_categories", "")
        block = f"{idx}. '{h.domain}': {h.description}"
        if example_cats:
            block += f"\n   Example categories: {example_cats}"
        domain_blocks.append(block)

    domains_text = "\n\n".join(domain_blocks)

    return (
        f"You are the {product_name} Tier-1 Intent and Domain Classifier.\n"
        "Your objective is to analyze the user inquiry and conversation context, then classify it into "
        "exactly one primary domain and an appropriate dot-notated subcategory.\n\n"
        "## Domains:\n"
        f"{domains_text}\n\n"
        "## Output Instructions:\n"
        f"- Set 'domain' to one of: {domains_quoted}.\n"
        "- Set 'category' to a dot-notated category matching the user's inquiry (e.g., 'operations.tasks', 'analytics.metrics').\n"
        "- Set 'reasoning' to a concise rationale explaining why the query belongs in this domain and category.\n"
        "Never attempt to answer domain questions directly; classify strictly for downstream specialist routing."
    )


TIER1_DOMAIN_CLASSIFIER_PROMPT = compose_tier1_classifier_prompt()



class OrchestratorDecision(BaseModel):
    """Structured output schema for the dynamic orchestrator routing decision."""

    agent_id: str = Field(
        ...,
        description="ID of the chosen specialist agent to delegate to, taken from the available agent list.",
    )
    reasoning: str = Field(
        ...,
        description="Clear, concise rationale explaining why this specialist was selected to address the user request.",
    )
    instructions: str = Field(
        default="",
        description="Specific instructions, extracted parameters, or focus areas for the delegated specialist agent.",
    )
    missing_skill: Optional[str] = Field(
        default=None,
        description="ID or name of any missing skill that should be generated for this request, or null if all required skills are present.",
    )
    missing_skill_description: Optional[str] = Field(
        default=None,
        description="Specific domain description, guidelines, and reference materials needed for the missing skill to be generated.",
    )
    required_docs: List[str] = Field(
        default_factory=list,
        description="Specific reference doc filenames (e.g. ['symptom_log_template.md', 'checklist.md']) needed by the specialist to address the user request.",
    )


def _turn_id(state: Dict[str, Any]) -> str:
    """The turn id set when the turn started, or a new one for direct node calls."""
    turn_id = state.get("turn_id")
    if not turn_id:
        turn_id = uuid.uuid4().hex
        state["turn_id"] = turn_id
    return str(turn_id)


_AGENT_SLUG = re.compile(r"^[a-z0-9_-]{1,64}$")

_NOTICE_TEXT = {
    "model_unavailable": "No model is configured, so the default agent took this turn.",
    "main_agent_failed": "Routing could not pick an agent, so the default agent took this turn.",
}


class OrchestratorNode(BaseNode):
    """Dynamic LLM-driven orchestrator node for multi-agent planning and routing."""

    def __init__(
        self,
        model: Optional[BaseChatModel] = None,
        registry: Optional[AgentRegistry] = None,
        catalog: Optional[CatalogPort] = None,
        skill_generator: Optional[Any] = None,
        routing_hints: Optional[Sequence[RoutingHints]] = None,
        name: str = "orchestrator",
        default_agent: Optional[str] = None,
        orchestration: Optional[PackOrchestrationSpec] = None,
        main_agent_enabled: bool = False,
        audit_sink: Optional[AuditSink] = None,
    ) -> None:
        super().__init__(name=name)
        self.model = model
        # Receives the ``route.*`` record of each directly routed turn (strict).
        self.audit_sink = audit_sink
        # Pack orchestration config: fixed routes run before any model call.
        self.orchestration = orchestration
        # When set, model-routed turns go to the main agent node (task tool).
        self.main_agent_enabled = main_agent_enabled
        # Pack-configured fallback (orchestration.default_agent). Core has no
        # default of its own: when this is unset and routing cannot pick a
        # registered agent, the turn fails with an error.
        self.default_agent = (
            (default_agent or "").strip()
            or (orchestration.default_agent if orchestration is not None else "")
        ) or None
        self._registry = registry
        self.catalog = catalog
        self._skill_generator = skill_generator
        self.routing_hints = routing_hints
        if routing_hints is not None:
            prod_name = getattr(settings, "product_name", "Yarvelle Core")
            self.tier1_prompt = compose_tier1_classifier_prompt(routing_hints, product_name=prod_name)
        else:
            self.tier1_prompt = TIER1_DOMAIN_CLASSIFIER_PROMPT

    @property
    def skill_generator(self) -> Any:
        """Lazily resolves SkillGeneratorNode instance."""
        if self._skill_generator is None:
            from yarvelle_core.workflows.nodes.skill_generator_node import SkillGeneratorNode
            self._skill_generator = SkillGeneratorNode(
                model=self.model,
                skills_dir=self.registry._skills_dir,
            )
        return self._skill_generator

    @property
    def registry(self) -> AgentRegistry:
        """Lazily resolves AgentRegistry from workspace root if not explicitly injected."""
        if self._registry is None:
            agents_dir = settings.get_agents_dir()
            skills_dir = settings.get_skills_dir()
            self._registry = AgentRegistry(
                agents_dir=agents_dir,
                skills_dir=skills_dir if skills_dir.is_dir() else None,
            )
        return self._registry

    def _format_candidate_agents(self, candidates: List[AgentManifest]) -> str:
        """Formats retrieved candidate agents for Tier-2 prompt."""
        blocks: List[str] = []
        for agent in candidates:
            domain_val = agent.domain.value if hasattr(agent.domain, "value") else str(agent.domain)
            cat_val = agent.category or ""
            tools_val = ", ".join(agent.tools) if agent.tools else "none"
            desc = agent.description or _extract_first_line(agent.persona)
            blocks.append(
                f"- **{agent.id}** ({agent.title}) [Domain: {domain_val}, Category: {cat_val}]\n"
                f"  Description: {desc}\n"
                f"  Tools: [{tools_val}]"
            )
        return "\n".join(blocks)

    def _build_tier2_system_prompt(self, candidates: List[AgentManifest]) -> str:
        """Assembles Tier-2 system prompt targeting candidate agents from catalog via Handlebars."""
        candidate_catalog = self._format_candidate_agents(candidates)
        prompts = get_resource_loader().get_prompts()
        base_prompt = (
            prompts.get("orchestrator", {}).get("system_prompt")
            or prompts.get("supervisor", {}).get("system_prompt")
            or (
                "You are the Yarvelle Core Orchestrator, an intelligent routing and planning coordinator.\n"
                "Analyze the conversation, user intent, and available candidate specialist agents to determine the best specialist to handle the request.\n"
                "Delegate to the single most appropriate specialist. Never answer domain-specific questions yourself."
            )
        )
        context = {
            "base_prompt": base_prompt.strip(),
            "heading": "Candidate Specialist Agents",
            "catalog": candidate_catalog,
            "target_list_name": "candidate list",
        }
        return render_template("orchestrator_routing_prompt", context)

    def _build_system_prompt(self, state: Dict[str, Any]) -> str:
        """Assembles orchestrator system prompt incorporating dynamic agent catalog from registry via Handlebars."""
        catalog = self.registry.format_agent_catalog(exclude=AGENT_ORCHESTRATOR)
        prompts = get_resource_loader().get_prompts()
        base_prompt = (
            prompts.get("orchestrator", {}).get("system_prompt")
            or prompts.get("supervisor", {}).get("system_prompt")
            or (
                "You are the Yarvelle Core Orchestrator, an intelligent routing and planning coordinator.\n"
                "Analyze the conversation, user intent, and available specialist agents to determine the best specialist to handle the request.\n"
                "Delegate to the single most appropriate specialist. Never answer domain-specific questions yourself."
            )
        )
        context = {
            "base_prompt": base_prompt.strip(),
            "heading": "Available Specialist Agents",
            "catalog": catalog,
            "target_list_name": "catalog",
        }
        return render_template("orchestrator_routing_prompt", context)

    def _fallback_to_default(self, reason: str, turn_state: Dict[str, Any]) -> Optional[OrchestratorDecision]:
        """Routes to the pack default agent and records an orchestration notice."""
        if not self.default_agent:
            return None
        notice = {
            "type": "orchestration_notice",
            "turn_id": _turn_id(turn_state),
            "code": reason,
            "message": _NOTICE_TEXT[reason],
            "agent_ids": [self.default_agent],
        }
        # Never append in place: the list may be shared with the graph state.
        turn_state["orchestration_notices"] = list(turn_state.get("orchestration_notices") or []) + [notice]
        turn_state["route_decision"] = RouteDecision(
            source=RouteSource.DEFAULT_AGENT, agent_id=self.default_agent, fallback_reason=reason,  # type: ignore[arg-type]
        ).model_dump(mode="json", exclude_none=True)
        return OrchestratorDecision(
            agent_id=self.default_agent,
            reasoning=f"Default agent ({reason}).",
            instructions="",
        )

    async def _record_route(self, state: Dict[str, Any], decision: Optional[Dict[str, Any]]) -> None:
        """Writes the turn's ``route.*`` audit record; a failed write stops the turn."""
        if not decision:
            return
        await record_route(
            self.audit_sink,
            RouteDecision.model_validate(decision),
            _turn_id(state),
            str(state["thread_id"]) if state.get("thread_id") else None,
        )

    async def _reject_hidden_pick(self, state: Dict[str, Any]) -> Optional[str]:
        """Refuses a caller's pick of a hidden agent; returns the refused id.

        Hidden agents only run when routing sends work to them. The pick is
        dropped, a ``route.rejected`` record is written, and the turn is
        routed as if nothing had been picked (fixed routes, then the main
        agent or the routing model, then the default agent).
        """
        pick = state.get("explicit_agent")
        if not pick or str(pick) in ("orchestrator", "supervisor", "unknown"):
            return None
        pick = str(pick).strip()
        if pick_rejection(self.registry, pick) != "hidden":
            return None
        logger.warning("Refused a direct pick of hidden agent '%s'; routing the turn instead", pick)
        await record_rejected_pick(
            self.audit_sink,
            pick,
            "hidden",
            _turn_id(state),
            str(state["thread_id"]) if state.get("thread_id") else None,
        )
        return pick

    def _no_route_error(self, reason: str) -> Dict[str, Any]:
        """Returns an error state when no agent can be chosen and no pack default is set."""
        err_msg = (
            f"Could not route the request: {reason}, and no default agent is configured "
            "(set orchestration.default_agent in the pack)."
        )
        logger.error(err_msg)
        return {"error": err_msg, "next_step": "error"}

    async def _execute_single_hop(
        self,
        state: Dict[str, Any],
        prompt_text: str,
        raw_messages: List[Any],
    ) -> Optional[OrchestratorDecision]:
        """Executes legacy single-hop dynamic catalog prompt and structured decision.

        Returns None when the model gives no usable decision.
        """
        system_prompt = self._build_system_prompt(state)
        lc_messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]

        for m in raw_messages:
            if isinstance(m, BaseMessage):
                lc_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    lc_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    lc_messages.append(AIMessage(content=content))
                elif role == "system":
                    lc_messages.append(SystemMessage(content=content))

        decision = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(OrchestratorDecision)
                    res = await structured_model.ainvoke(
                        lc_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, OrchestratorDecision):
                        decision = res
                    elif isinstance(res, dict):
                        decision = OrchestratorDecision(**res)
                except Exception as structured_err:
                    logger.debug("with_structured_output failed: %s", structured_err)
                    decision = None

            if decision is None:
                resp = await self.model.ainvoke(
                    lc_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        decision = OrchestratorDecision(**data)
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Orchestrator structured model call failed (%s); triggering fallback", exc)
            decision = None

        # No usable answer: the caller hands the turn to the default agent
        # with a notice and a ``route.default`` record.
        return decision

    async def _execute_two_hop(
        self,
        state: Dict[str, Any],
        prompt_text: str,
        raw_messages: List[Any],
    ) -> Tuple[Optional[OrchestratorDecision], List[AgentManifest]]:
        """Executes Tier-1 Domain Classification followed by Tier-2 Specialist Picking via CatalogPort.

        The decision is None when no candidate or no usable pick came back.
        """
        # 1. Tier-1 Domain Classifier invokes model.with_structured_output(DomainClassification)
        tier1_messages: List[BaseMessage] = [SystemMessage(content=self.tier1_prompt)]
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                tier1_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    tier1_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    tier1_messages.append(AIMessage(content=content))
                elif role == "system":
                    tier1_messages.append(SystemMessage(content=content))
        if not any(
            isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") in ("user", "human"))
            for m in raw_messages
        ):
            if prompt_text:
                tier1_messages.append(HumanMessage(content=prompt_text))

        classified: Optional[DomainClassification] = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(DomainClassification)
                    res = await structured_model.ainvoke(
                        tier1_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, DomainClassification):
                        classified = res
                    elif isinstance(res, dict):
                        classified = DomainClassification(**res)
                except Exception as tier1_err:
                    logger.debug("Tier-1 with_structured_output failed: %s", tier1_err)
                    classified = None

            if classified is None:
                resp = await self.model.ainvoke(
                    tier1_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        classified = DomainClassification(**data)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Tier-1 domain classification model call failed: %s", exc)
            classified = None

        # 2. Fallback chain on CatalogPort
        candidates: List[AgentManifest] = []
        if self.catalog is not None and classified is not None:
            domain_val = classified.domain.strip() if classified.domain else ""
            cat_val = classified.category.strip() if classified.category else ""
            # Step 1: Search by domain and category
            if domain_val:
                search_cat = cat_val
                if search_cat and "." not in search_cat:
                    search_cat = f"{domain_val}.{search_cat}"
                candidates = await self.catalog.search_agents(
                    domain=domain_val,
                    category=search_cat,
                    limit=8,
                )
                if not candidates and search_cat != cat_val:
                    candidates = await self.catalog.search_agents(
                        domain=domain_val,
                        category=cat_val,
                        limit=8,
                    )
                # Step 2: If 0 candidates, search by domain only
                if not candidates:
                    candidates = await self.catalog.search_agents(
                        domain=domain_val,
                        limit=8,
                    )

        # Step 3: If 0 candidates, search by FTS query on tags/prompt
        if not candidates and self.catalog is not None:
            candidates = await self.catalog.search_agents(
                query=prompt_text,
                limit=8,
            )

        # Step 4: no candidates; the caller falls back to the default agent
        if not candidates:
            return None, []

        # 3. Tier-2 Specialist Picker targeting candidate set
        tier2_prompt = self._build_tier2_system_prompt(candidates)
        tier2_messages: List[BaseMessage] = [SystemMessage(content=tier2_prompt)]
        for m in raw_messages:
            if isinstance(m, BaseMessage):
                tier2_messages.append(m)
            elif isinstance(m, dict):
                role = m.get("role", "")
                content = str(m.get("content", ""))
                if role in ("user", "human"):
                    tier2_messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    tier2_messages.append(AIMessage(content=content))
                elif role == "system":
                    tier2_messages.append(SystemMessage(content=content))
        if not any(
            isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get("role") in ("user", "human"))
            for m in raw_messages
        ):
            if prompt_text:
                tier2_messages.append(HumanMessage(content=prompt_text))

        decision: Optional[OrchestratorDecision] = None
        try:
            if hasattr(self.model, "with_structured_output"):
                try:
                    structured_model = self.model.with_structured_output(OrchestratorDecision)
                    res = await structured_model.ainvoke(
                        tier2_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                    )
                    if isinstance(res, OrchestratorDecision):
                        decision = res
                    elif isinstance(res, dict):
                        decision = OrchestratorDecision(**res)
                except Exception as tier2_err:
                    logger.debug("Tier-2 with_structured_output failed: %s", tier2_err)
                    decision = None

            if decision is None:
                resp = await self.model.ainvoke(
                    tier2_messages, config={"tags": ["internal", "orchestrator", "no_stream"]}
                )
                content = extract_text_content(resp)
                import json
                clean_content = content.strip()
                if clean_content.startswith("```"):
                    import re
                    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                    if m_block:
                        clean_content = m_block.group(1).strip()
                try:
                    data = json.loads(clean_content)
                    if isinstance(data, dict):
                        decision = OrchestratorDecision(**data)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Tier-2 specialist picker model call failed (%s); using candidate fallback", exc)
            decision = None

        return decision, candidates

    def _route(
        self,
        target_agent: str,
        prompt_text: str,
        state: Dict[str, Any],
        decision: Optional[OrchestratorDecision] = None,
        candidates: Optional[List[AgentManifest]] = None,
        is_explicit: bool = False,
    ) -> ExecutionPlan:
        """Constructs a typed ExecutionPlan evaluating topological mode (single, parallel, pipeline, deliberate)."""
        if not is_explicit and state.get("explicit_agent"):
            is_explicit = True

        # 1. Respect pre-existing ExecutionPlan if present in state
        existing_plan = state.get("execution_plan")
        if isinstance(existing_plan, dict) and existing_plan.get("mode"):
            try:
                return ExecutionPlan.model_validate(existing_plan)
            except Exception:
                pass
        elif isinstance(existing_plan, ExecutionPlan):
            return existing_plan

        # 2. Structured deliberation request (panel or config set by the caller)
        deliberation_config = state.get("deliberation_config")
        panel_id = state.get("panel_id")
        if deliberation_config or panel_id:
            target_agents = [target_agent]
            if candidates:
                for c in candidates:
                    if c.id not in target_agents:
                        target_agents.append(c.id)
            if len(target_agents) >= 2:
                config_obj = (
                    DeliberationConfig.model_validate(deliberation_config)
                    if isinstance(deliberation_config, dict)
                    else (
                        deliberation_config
                        if isinstance(deliberation_config, DeliberationConfig)
                        else DeliberationConfig(panel_id=panel_id)
                    )
                )
                tasks = [
                    AgentTask(
                        agent_id=ag_id,
                        instructions=f"Deliberation proposal and peer critique for {ag_id}",
                        task_description=f"Deliberation round for {ag_id}",
                        priority=1,
                    )
                    for ag_id in target_agents
                ]
                return ExecutionPlan(
                    mode=ExecutionMode.DELIBERATE,
                    target_agents=target_agents,
                    tasks=tasks,
                    deliberation_config=config_obj,
                    reasoning=f"Multi-agent deliberation requested among: {', '.join(target_agents)}",
                )

        # 3. Single-agent mode (multi-agent work goes through the main agent)
        instructions = decision.instructions if decision and decision.instructions else ""
        reasoning = decision.reasoning if decision and decision.reasoning else f"Delegation to {target_agent}"
        return ExecutionPlan(
            mode=ExecutionMode.SINGLE,
            target_agents=[target_agent],
            tasks=[
                AgentTask(
                    agent_id=target_agent,
                    instructions=instructions,
                    task_description=instructions or f"Consultation with {target_agent}",
                    priority=1,
                )
            ],
            reasoning=reasoning,
        )

    async def _preflight_prepare_skills_and_docs(
        self,
        target_agent: str,
        missing_skill: Optional[str],
        missing_skill_description: str,
        required_docs: List[str],
        prompt_text: str,
        state: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
        """Proactively provisions missing skills and dynamically resolves reference docs from SkillManifest.references."""
        generated_skills = list(state.get("generated_skills", []))
        generated_skill = None
        provisioned_docs: List[str] = []
        provisioned_references: Dict[str, Dict[str, Any]] = dict(state.get("provisioned_references", {}))

        manifest = self.registry.get(target_agent)
        # 1. Detect missing skill
        if not missing_skill and manifest and manifest.skills:
            loaded_ids = {s.id for s in self.registry.get_loaded_skills(target_agent)}
            for sk_id in manifest.skills:
                if sk_id not in loaded_ids:
                    missing_skill = sk_id
                    missing_skill_description = f"Required declared skill '{sk_id}' for agent '{target_agent}' is missing."
                    break

        if missing_skill:
            logger.info("Orchestrator pre-flight provisioning missing skill '%s'", missing_skill)
            generated_skill = await self.skill_generator.generate_skill(
                skill_id=missing_skill,
                skill_description=missing_skill_description,
                user_query=prompt_text,
                target_agent=target_agent,
                state=state,
            )
            generated_skills.append(generated_skill)

        # 2. Generic Dynamic Reference Provisioner (Zero Hardcoding)
        # Identify all relevant target agents from execution plan or target_agent
        agents_to_scan = [target_agent]
        plan_dict = state.get("execution_plan")
        if isinstance(plan_dict, dict):
            for ag in plan_dict.get("target_agents", []):
                if ag not in agents_to_scan:
                    agents_to_scan.append(ag)

        explicit_reqs = set(required_docs) | set(state.get("required_docs", []))
        req_docs: List[str] = list(explicit_reqs)
        doc_skill_map: Dict[str, str] = {}
        prompt_lower = prompt_text.lower()

        # Dynamic scanning over declared SkillManifest.references
        for ag_id in agents_to_scan:
            ag_manifest = self.registry.get(ag_id)
            if not ag_manifest:
                continue
            for sk_id in (ag_manifest.skills or []):
                sk = self.registry.get_skill(sk_id)
                if not sk or not sk.references:
                    continue
                for ref_doc in sk.references:
                    ref_stem = Path(ref_doc).stem.replace("_", " ").replace("-", " ").lower()
                    stem_tokens = [tok for tok in re.findall(r"\w+", ref_stem) if len(tok) > 3]
                    if ref_doc in explicit_reqs or any(tok in prompt_lower for tok in stem_tokens):
                        if ref_doc not in req_docs:
                            req_docs.append(ref_doc)
                        doc_skill_map[ref_doc] = sk_id

        # Also inspect dynamically generated skills for references
        for gen_sk_item in generated_skills:
            g_id = gen_sk_item.get("id") or ""
            g_refs = gen_sk_item.get("references") or {}
            for ref_doc in g_refs.keys():
                ref_stem = Path(ref_doc).stem.replace("_", " ").replace("-", " ").lower()
                stem_tokens = [tok for tok in re.findall(r"\w+", ref_stem) if len(tok) > 3]
                if ref_doc in explicit_reqs or any(tok in prompt_lower for tok in stem_tokens):
                    if ref_doc not in req_docs:
                        req_docs.append(ref_doc)
                    doc_skill_map[ref_doc] = g_id

        # Fallback assignment for explicitly requested documents not yet tied to a skill
        for doc in req_docs:
            if doc not in doc_skill_map:
                target_sk = None
                if manifest and manifest.skills:
                    for sk_id in manifest.skills:
                        sk = self.registry.get_skill(sk_id)
                        if sk and (doc in sk.references or any(r.lower() == doc.lower() for r in sk.references)):
                            target_sk = sk_id
                            break
                    if target_sk is None:
                        other_skill_owns = False
                        for loaded_sk in getattr(self.registry, "_loaded_skills", {}).values():
                            for item in loaded_sk:
                                if item.id not in manifest.skills and (
                                    doc in item.references or any(r.lower() == doc.lower() for r in item.references)
                                ):
                                    other_skill_owns = True
                                    break
                            if other_skill_owns:
                                break
                        if not other_skill_owns:
                            target_sk = manifest.skills[0]
                doc_skill_map[doc] = target_sk or "general-reference"

        # Resolve target skills directory
        target_skills_dir = self.registry._skills_dir
        if not target_skills_dir:
            if state.get("skills_dir"):
                target_skills_dir = Path(state["skills_dir"]).resolve()
            elif state.get("workspace_root"):
                target_skills_dir = Path(state["workspace_root"]).resolve() / SKILLS_DIR
            else:
                target_skills_dir = settings.get_skills_dir().resolve()

        # Load matched reference documents with in-memory synthesis fallback
        for doc in req_docs:
            sk_id = doc_skill_map.get(doc, "general-reference")
            doc_title = Path(doc).stem.replace("_", " ").replace("-", " ").title()
            doc_content = ""

            # 1. Attempt to read file content from disk if available
            ref_file = target_skills_dir / sk_id / "references" / doc if target_skills_dir and sk_id else None
            if ref_file and ref_file.is_file():
                try:
                    doc_content = ref_file.read_text(encoding="utf-8")
                except Exception:
                    pass

            # 2. Check generated_skills in-memory reference map if present
            if not doc_content:
                for gen_sk_item in generated_skills:
                    refs_map = gen_sk_item.get("references") or {}
                    if doc in refs_map:
                        doc_content = refs_map[doc]
                        break

            # 3. If missing, synthesize via skill_generator
            if not doc_content and hasattr(self.skill_generator, "synthesize_reference_doc"):
                try:
                    synth_res = await self.skill_generator.synthesize_reference_doc(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                        state=state,
                    )
                    doc_content = synth_res.get("content", "")
                except Exception as synth_err:
                    logger.warning("SkillGenerator synthesis error for '%s': %s", doc, synth_err)

            if not doc_content and hasattr(self.skill_generator, "ensure_reference_doc"):
                try:
                    p = await self.skill_generator.ensure_reference_doc(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                        state=state,
                    )
                    if p and Path(p).is_file():
                        doc_content = Path(p).read_text(encoding="utf-8")
                except Exception as ensure_err:
                    logger.warning("ensure_reference_doc error: %s", ensure_err)

            # 4. Guaranteed in-memory fallback
            if not doc_content:
                if hasattr(self.skill_generator, "synthesize_reference_doc_content"):
                    doc_content = self.skill_generator.synthesize_reference_doc_content(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                    )
                elif hasattr(self.skill_generator, "_synthesize_reference_doc_content"):
                    doc_content = self.skill_generator._synthesize_reference_doc_content(
                        skill_id=sk_id,
                        doc_name=doc,
                        user_query=prompt_text,
                        target_agent=target_agent,
                    )
                else:
                    doc_content = f"# {doc_title}\nSynthesized reference document."

            provisioned_references[doc] = {
                "title": doc_title,
                "content": doc_content,
                "skill_id": sk_id,
            }
            provisioned_docs.append(doc)

        state["provisioned_references"] = provisioned_references
        state["provisioned_docs"] = list(provisioned_references.keys())

        # 3. Reload registry if any skill or doc was provisioned
        if missing_skill or provisioned_docs:
            try:
                self.registry.reload()
            except Exception:
                pass

        return generated_skills, generated_skill, provisioned_docs

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Classifies user intent, selects specialist agent, and outputs routing state."""
        # Extract last human prompt text early for context
        prompt_text = ""
        for m in reversed(state.get("messages", [])):
            if isinstance(m, dict) and m.get("role") in ("user", "human"):
                prompt_text = str(m.get("content") or "")
                break
            elif isinstance(m, HumanMessage) or (isinstance(m, BaseMessage) and getattr(m, "type", "") in ("human", "user")):
                prompt_text = str(getattr(m, "content", "") or "")
                break
        if not prompt_text and state.get("prompt"):
            prompt_text = str(state.get("prompt"))

        # 1. Explicit routing bypass (e.g., user selected agent in UI or pre-routed system state)
        rejected = await self._reject_hidden_pick(state)
        explicit = state.get("explicit_agent") or state.get("routed_subgraph") or state.get("current_agent")
        if rejected is not None and explicit == rejected:
            explicit = None
        if explicit and explicit not in ("orchestrator", "supervisor", "unknown"):
            raw_explicit = str(explicit).strip()
            if self.registry.get(raw_explicit) is not None:
                normalized = raw_explicit
            elif raw_explicit.startswith("_"):
                normalized = raw_explicit.lower()
            else:
                normalized = raw_explicit.lower().replace("_", "-")

            # Route execution plan with explicit flag
            plan = self._route(
                target_agent=normalized,
                prompt_text=prompt_text,
                state=state,
                is_explicit=True,
            )
            state["execution_plan"] = plan.model_dump(mode="json")
            route_decision: Optional[Dict[str, Any]] = None
            if _AGENT_SLUG.match(normalized):
                route_decision = RouteDecision(source=RouteSource.USER_SELECTED, agent_id=normalized).model_dump(
                    mode="json", exclude_none=True
                )
                await self._record_route(state, route_decision)

            # Pre-flight check and provision skills and docs for explicit target
            missing_sk = state.get("missing_skill") or state.get("required_skill")
            gen_skills, gen_sk, prov_docs = await self._preflight_prepare_skills_and_docs(
                target_agent=normalized,
                missing_skill=missing_sk,
                missing_skill_description=state.get("missing_skill_description", ""),
                required_docs=state.get("required_docs", []),
                prompt_text=prompt_text,
                state=state,
            )

            res_dict: Dict[str, Any] = {
                "current_agent": normalized,
                "routed_subgraph": normalized,
                "agent_id": normalized,
                "orchestrator_reasoning": "Explicitly requested by user or pre-routed system state.",
                "orchestrator_instructions": state.get("orchestrator_instructions", ""),
                "next_step": normalized,
                "execution_plan": plan.model_dump(mode="json"),
                "provisioned_references": state.get("provisioned_references", {}),
                "provisioned_docs": list(state.get("provisioned_references", {}).keys()),
            }
            if route_decision is not None:
                res_dict["route_decision"] = route_decision
            if gen_skills:
                res_dict["generated_skills"] = gen_skills
            if gen_sk:
                res_dict["generated_skill"] = gen_sk
            return res_dict

        # 2. Pack fixed routes, evaluated before any model call
        fixed = select_fixed_route(self.orchestration, state)
        builtin_doc_route = (
            fixed is None
            and self.orchestration is None
            and has_attachments(state)
            and self.registry.get(AGENT_DOCUMENT_EXTRACTOR) is not None
        )
        candidates: List[AgentManifest] = []
        raw_messages = list(state.get("messages", []))
        decision: Optional[OrchestratorDecision]
        classified = False
        if rejected is not None:
            # A refused pick must not leave the pinned agent in place.
            state["explicit_agent"] = None
            state["current_agent"] = None
            state["routed_subgraph"] = None
        # A decision left from an earlier pass is never this pass's route.
        state["route_decision"] = None

        if fixed is not None and fixed.agent_id:
            decision = OrchestratorDecision(
                agent_id=fixed.agent_id,
                reasoning=f"Fixed route '{fixed.route_id}'.",
                instructions="",
            )
            state["route_decision"] = fixed.model_dump(mode="json", exclude_none=True)
        elif builtin_doc_route:
            # Without pack routes, attachments go to the built-in document agent.
            decision = OrchestratorDecision(
                agent_id=AGENT_DOCUMENT_EXTRACTOR,
                reasoning="Turn carries attachments.",
                instructions="",
            )
            state["route_decision"] = RouteDecision(
                source=RouteSource.FIXED_ROUTE,
                route_id=BUILTIN_DOCUMENT_ROUTE_ID,
                agent_id=AGENT_DOCUMENT_EXTRACTOR,
            ).model_dump(mode="json", exclude_none=True)
        elif self.model is None:
            # No model: the pack default takes the turn, with a notice. Never a guess.
            decision = self._fallback_to_default("model_unavailable", state)
            if decision is None:
                return self._no_route_error("no model is configured")
        elif self.main_agent_enabled:
            # The main agent hands work to registered agents through the task tool.
            out: Dict[str, Any] = {
                "current_agent": MAIN_AGENT_ID,
                "routed_subgraph": MAIN_AGENT_ID,
                "agent_id": MAIN_AGENT_ID,
                "orchestrator_reasoning": "Main agent coordinates this turn.",
                "orchestrator_instructions": "",
                "next_step": MAIN_AGENT_ID,
            }
            if rejected is not None:
                out["explicit_agent"] = None
            return out
        elif self.catalog is None:
            decision = await self._execute_single_hop(state, prompt_text, raw_messages)
            classified = True
        else:
            decision, candidates = await self._execute_two_hop(state, prompt_text, raw_messages)
            classified = True

        if decision is None or not str(decision.agent_id).strip():
            decision = self._fallback_to_default("main_agent_failed", state)
            if decision is None:
                return self._no_route_error("routing produced no agent")

        # 3. The selected agent must be registered; no silent substitution
        selected_id = str(decision.agent_id).strip().lower().replace("_", "-")
        candidate_ids = {c.id for c in candidates} if candidates else set()
        is_default = bool(self.default_agent) and selected_id == self.default_agent
        if not is_default and not self.registry.get(selected_id) and selected_id not in candidate_ids:
            fallback = self._fallback_to_default("main_agent_failed", state)
            if fallback is None:
                return self._no_route_error(f"routing chose unknown agent '{decision.agent_id}'")
            fallback.reasoning = f"Routing chose unknown agent '{decision.agent_id}'; default agent took the turn."
            decision = fallback
            selected_id = str(decision.agent_id)

        # Route execution plan
        plan = self._route(
            target_agent=selected_id,
            prompt_text=prompt_text,
            state=state,
            decision=decision,
            candidates=candidates,
            is_explicit=False,
        )
        state["execution_plan"] = plan.model_dump(mode="json")

        # 4. Pre-flight check: provision any missing skills or required reference documents before specialist execution
        missing_skill_name = (
            getattr(decision, "missing_skill", None)
            or state.get("missing_skill")
            or state.get("required_skill")
        )
        missing_skill_desc = (
            getattr(decision, "missing_skill_description", None)
            or state.get("missing_skill_description", "")
        )
        required_docs = list(getattr(decision, "required_docs", []) or [])

        generated_skills, generated_skill, provisioned_docs = await self._preflight_prepare_skills_and_docs(
            target_agent=selected_id,
            missing_skill=missing_skill_name,
            missing_skill_description=missing_skill_desc,
            required_docs=required_docs,
            prompt_text=prompt_text,
            state=state,
        )

        effective_agent = plan.target_agents[0] if plan.target_agents else selected_id
        if classified and not state.get("route_decision") and _AGENT_SLUG.match(effective_agent):
            # The routing model picked the agent: record it like any other route.
            state["route_decision"] = RouteDecision(
                source=RouteSource.MODEL_CLASSIFIED, agent_id=effective_agent
            ).model_dump(mode="json", exclude_none=True)

        result_payload: Dict[str, Any] = {
            "current_agent": effective_agent,
            "routed_subgraph": effective_agent,
            "agent_id": effective_agent,
            "orchestrator_reasoning": decision.reasoning,
            "orchestrator_instructions": decision.instructions,
            "next_step": effective_agent,
            "execution_plan": plan.model_dump(mode="json"),
            "provisioned_references": state.get("provisioned_references", {}),
            "provisioned_docs": list(state.get("provisioned_references", {}).keys()),
        }
        if rejected is not None:
            result_payload["explicit_agent"] = None
        if state.get("orchestration_notices"):
            result_payload["orchestration_notices"] = list(state["orchestration_notices"])
        if state.get("route_decision"):
            result_payload["route_decision"] = state["route_decision"]
            await self._record_route(state, state["route_decision"])
        if generated_skills:
            result_payload["generated_skills"] = generated_skills
        if generated_skill:
            result_payload["generated_skill"] = generated_skill

        return result_payload


__all__ = [
    "DomainClassification",
    "OrchestratorDecision",
    "OrchestratorNode",
    "TIER1_DOMAIN_CLASSIFIER_PROMPT",
    "compose_tier1_classifier_prompt",
    "DEFAULT_ROUTING_HINTS",
]

