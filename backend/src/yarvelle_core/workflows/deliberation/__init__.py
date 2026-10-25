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

"""Bounded Multi-Agent Blackboard Deliberation Engine & Budget Auditor (Milestone 2 / R2).

Provides:
- DeliberationEngine: Multi-round blackboard deliberation coordinator.
- BlackboardManager / DeliberationBlackboard: In-memory blackboard state manager.
- BudgetAuditor, UnitMismatchError: Deterministic constraint budget auditor.
- evaluate_convergence_gate, ConvergenceGate, ConvergenceDecision: Rule-based convergence gate.
- run_peer_critiques: Disagree-or-Commit peer review (per_agent and batched modes).
- run_selective_revision: Targeted specialist delta revision.
- generate_agent_proposal, run_propose_phase: Round 1 proposal generation with schema repair.
- evaluate_deliberation_tool_gate, filter_read_only_tools: Read-only tool execution policy.
- create_deliberation_subgraph: Compiled LangGraph StateGraph builder.
"""

from __future__ import annotations

from yarvelle_core.workflows.deliberation.auditor import BudgetAuditor, UnitMismatchError
from yarvelle_core.workflows.deliberation.blackboard import BlackboardManager, DeliberationBlackboard
from yarvelle_core.workflows.deliberation.doc_critique import run_peer_critiques
from yarvelle_core.workflows.deliberation.engine import BudgetDecision, DeliberationEngine
from yarvelle_core.workflows.deliberation.gate import (
    ConvergenceDecision,
    ConvergenceGate,
    evaluate_convergence_gate,
)
from yarvelle_core.workflows.deliberation.propose import generate_agent_proposal, run_propose_phase
from yarvelle_core.workflows.deliberation.revise import run_selective_revision
from yarvelle_core.workflows.deliberation.subgraph import create_deliberation_subgraph
from yarvelle_core.workflows.deliberation.tool_gate import (
    evaluate_deliberation_tool_gate,
    filter_read_only_tools,
)

__all__ = [
    "BlackboardManager",
    "BudgetAuditor",
    "BudgetDecision",
    "ConvergenceDecision",
    "ConvergenceGate",
    "DeliberationBlackboard",
    "DeliberationEngine",
    "UnitMismatchError",
    "create_deliberation_subgraph",
    "evaluate_convergence_gate",
    "evaluate_deliberation_tool_gate",
    "filter_read_only_tools",
    "generate_agent_proposal",
    "run_peer_critiques",
    "run_propose_phase",
    "run_selective_revision",
]
