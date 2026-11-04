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

"""Core agent identifiers, defaults, and delegation constants.

Centralizes all agent IDs, tool identifiers, risk classes, and orchestration
execution defaults, eliminating hardcoded string literals across runtime nodes.
"""

from __future__ import annotations

from typing import FrozenSet

# ============================================================================
# 1. Agent Identifiers
# ============================================================================

AGENT_ORCHESTRATOR: str = "orchestrator"
AGENT_DOCUMENT_EXTRACTOR: str = "document-extractor"
AGENT_DB_OPERATOR: str = "db-operator"
AGENT_SKILL_GENERATOR: str = "skill-generator"
AGENT_SUGGESTION_GENERATOR: str = "suggestion-generator"
AGENT_TEMPLATE: str = "_template"

# System agents shipped with core (agents/_system). Domain agents come from
# packs; core never names them and never falls back to one.
BUNDLED_AGENT_IDS: FrozenSet[str] = frozenset({
    AGENT_ORCHESTRATOR,
    AGENT_DOCUMENT_EXTRACTOR,
    AGENT_DB_OPERATOR,
    AGENT_SKILL_GENERATOR,
    AGENT_SUGGESTION_GENERATOR,
})
ALL_BUNDLED_AGENT_IDS: FrozenSet[str] = BUNDLED_AGENT_IDS

# Attribution label for audit records and notes written without an agent in
# context. It is never used to pick an agent to run.
UNKNOWN_AGENT_ID: str = "unknown"


# ============================================================================
# 2. Tool Identifiers
# ============================================================================

# Phase 0 Closed Tools
TOOL_ATTACH_READ: str = "attach-read"
TOOL_WORKSPACE_NOTE: str = "workspace-note"
TOOL_SKILL_DOCS: str = "skill-docs"
TOOL_SEARCH_RECORDS: str = "search_records"

# Delegation Meta-Tools
TOOL_DELEGATE_TO_AGENT: str = "delegate_to_agent"
TOOL_LIST_AGENTS: str = "list_agents"

DELEGATION_TOOLS: FrozenSet[str] = frozenset({
    TOOL_DELEGATE_TO_AGENT,
    TOOL_LIST_AGENTS,
})

# Extraction Tools
TOOL_SANITIZE_PII: str = "sanitize_pii"
TOOL_EXTRACT_STRUCTURED_DATA: str = "extract_structured_data"
TOOL_VALIDATE_GROUNDING: str = "validate_grounding"
TOOL_EXTRACT_DOCUMENT_DOSSIER: str = "extract_document_dossier"

EXTRACTION_TOOLS: FrozenSet[str] = frozenset({
    TOOL_ATTACH_READ,
    TOOL_SANITIZE_PII,
    TOOL_EXTRACT_STRUCTURED_DATA,
    TOOL_VALIDATE_GROUNDING,
    TOOL_EXTRACT_DOCUMENT_DOSSIER,
})

EXPANDED_PHASE_0_REGISTRY: FrozenSet[str] = frozenset({
    TOOL_ATTACH_READ,
    TOOL_WORKSPACE_NOTE,
    TOOL_SKILL_DOCS,
    TOOL_SEARCH_RECORDS,
    TOOL_DELEGATE_TO_AGENT,
    TOOL_LIST_AGENTS,
    TOOL_SANITIZE_PII,
    TOOL_EXTRACT_STRUCTURED_DATA,
    TOOL_VALIDATE_GROUNDING,
    TOOL_EXTRACT_DOCUMENT_DOSSIER,
    "db_inspect_schema",
    "db_execute_query",
    "db_mutate_records",
    "upsert_workspace_note",
    "list_workspace_notes",
    "get_workspace_note",
    "delete_workspace_note",
    "create_profile_reminder",
    "list_profile_reminders",
    "update_profile_reminder",
    "create_email_draft_record",
    "list_email_draft_records",
})


# ============================================================================
# 3. Agent Risk Classes
# ============================================================================

RISK_CLASS_ADMIN: str = "admin"
RISK_CLASS_WELLNESS: str = "wellness"
RISK_CLASS_CLINICAL_ASSIST: str = "clinical_assist"
RISK_CLASS_EDUCATION: str = "education"


# ============================================================================
# 4. Orchestration & Iteration Limits
# ============================================================================

DEFAULT_CAN_DELEGATE: bool = False
DEFAULT_MAX_ITERATIONS: int = 3
DEFAULT_ORCHESTRATOR_MAX_ITERATIONS: int = 5
ORCHESTRATOR_MAX_ITERATIONS: int = 5

__all__ = [
    "AGENT_DB_OPERATOR",
    "AGENT_DOCUMENT_EXTRACTOR",
    "AGENT_ORCHESTRATOR",
    "AGENT_SKILL_GENERATOR",
    "AGENT_SUGGESTION_GENERATOR",
    "AGENT_TEMPLATE",
    "ALL_BUNDLED_AGENT_IDS",
    "BUNDLED_AGENT_IDS",
    "DEFAULT_CAN_DELEGATE",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_ORCHESTRATOR_MAX_ITERATIONS",
    "DELEGATION_TOOLS",
    "EXPANDED_PHASE_0_REGISTRY",
    "EXTRACTION_TOOLS",
    "ORCHESTRATOR_MAX_ITERATIONS",
    "RISK_CLASS_ADMIN",
    "RISK_CLASS_CLINICAL_ASSIST",
    "RISK_CLASS_EDUCATION",
    "RISK_CLASS_WELLNESS",
    "TOOL_ATTACH_READ",
    "TOOL_DELEGATE_TO_AGENT",
    "TOOL_EXTRACT_DOCUMENT_DOSSIER",
    "TOOL_EXTRACT_STRUCTURED_DATA",
    "TOOL_LIST_AGENTS",
    "TOOL_SANITIZE_PII",
    "TOOL_SEARCH_RECORDS",
    "TOOL_SKILL_DOCS",
    "TOOL_VALIDATE_GROUNDING",
    "TOOL_WORKSPACE_NOTE",
    "UNKNOWN_AGENT_ID",
]
