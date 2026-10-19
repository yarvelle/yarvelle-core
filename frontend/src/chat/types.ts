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
  reasoning?: string;
}

export interface ChatSlotHooks {
  beforeSend?: (content: string, attachments: ChatAttachment[]) => Promise<boolean | string>;
  composerAction?: React.ReactNode;
  messageRenderer?: (message: ChatMessage) => React.ReactNode;
}
