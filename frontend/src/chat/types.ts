// Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
// Copyright 2026 Spectrayan (https://spectrayan.com)
//
// Licensed under the PolyForm Noncommercial License 1.0.0 and the
// Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
// Personal and household local use only. Commercial use, hosted service
// offering, rebranding, white-labeling, and redistribution of modified
// forks are prohibited without a written commercial license from Spectrayan.
//
// Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

import * as React from 'react';

export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageStatus = 'sending' | 'sent' | 'streaming' | 'error';
export type RiskLevel = 'info' | 'warn' | 'danger';

export interface ChatAttachment {
  id: string;
  name: string;
  mimeType?: string;
  sizeBytes?: number;
  url?: string;
}

export interface ToolCallTrace {
  id: string;
  toolName: string;
  input?: Record<string, unknown> | string;
  output?: Record<string, unknown> | string;
  status: 'running' | 'success' | 'error';
  durationMs?: number;
}

export interface ExecutionPlanStep {
  id: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

export interface ApprovalRequest {
  id: string;
  level: RiskLevel;
  label: string;
  details?: Record<string, unknown>;
  status?: 'pending' | 'approved' | 'rejected';
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  status?: MessageStatus;
  authorName?: string;
  avatarUrl?: string;
  attachments?: ChatAttachment[];
  toolTraces?: ToolCallTrace[];
  executionPlan?: ExecutionPlanStep[];
  approval?: ApprovalRequest;
  roundtable?: DeliberationRoundtableData;
  reasoning?: string;
}

export type DeliberationCritiqueStance = 'endorse' | 'complement' | 'amend' | 'conflict';

export type DeliberationIssueType =
  | 'resource_overbudget'
  | 'contraindication'
  | 'dependency_order'
  | 'synergy'
  | 'risk_exposure'
  | string;

export type StagedActionRiskTier = 'read' | 'write_local' | 'write_external' | 'irreversible';

export interface DeliberationConstraint {
  id: string;
  description?: string;
  unit: string;
  limit_value?: number | null;
  limit_source?: 'user' | 'profile' | null;
  total_claimed?: number;
  skipped?: boolean;
}

export interface StagedActionItem {
  id?: string;
  agent_id: string;
  tool_name: string;
  tool_args?: Record<string, unknown>;
  rationale?: string;
  risk_tier: StagedActionRiskTier;
  status?: 'pending' | 'approved' | 'rejected';
}

export interface DeliberationSpecialistProposal {
  agent_id: string;
  round_num: number;
  scope?: string;
  summary: string;
  recommendations?: string[];
  resource_claims?: Record<string, number>;
  resource_claim_units?: Record<string, string>;
  dependencies?: string[];
  staged_actions?: StagedActionItem[];
  tainted?: boolean;
  confidence?: number | null;
}

export interface DeliberationPeerCritique {
  reviewer_agent_id: string;
  target_agent_id: string;
  round_num: number;
  stance: DeliberationCritiqueStance;
  issue_type: DeliberationIssueType;
  critique: string;
  proposed_resolution: string;
  resolved?: boolean;
}

export interface DeliberationMinorityReportItem {
  issue_type: string;
  target_agent_id: string;
  reviewer_agent_id: string;
  target_position: string;
  target_recommendations?: string[];
  reviewer_critique: string;
  reviewer_proposed_resolution: string;
}

export interface DeliberationRoundtableData {
  panel_id?: string;
  title?: string;
  agents: string[];
  shared_constraints?: DeliberationConstraint[];
  skipped_constraints?: string[];
  proposals?: Record<number, Record<string, DeliberationSpecialistProposal>> | DeliberationSpecialistProposal[];
  critiques?: Record<number, DeliberationPeerCritique[]> | DeliberationPeerCritique[];
  staged_actions?: StagedActionItem[];
  rounds_used?: number;
  converged?: boolean;
  termination_reason?: 'converged' | 'max_rounds' | 'budget' | 'cancelled' | string;
  minority_reports?: DeliberationMinorityReportItem[];
  open_amendments?: DeliberationPeerCritique[];
}

export interface DeliberationRoundtableProps extends DeliberationRoundtableData {
  className?: string;
  onApproveStagedAction?: (id: string, decision: 'approved' | 'rejected') => Promise<void> | void;
}

export interface ChatSlotHooks {
  beforeSend?: (content: string, attachments: ChatAttachment[]) => Promise<boolean | string>;
  composerAction?: React.ReactNode;
  messageRenderer?: (message: ChatMessage) => React.ReactNode;
}

