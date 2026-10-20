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

export type AudienceBand = 'adult' | 'teen' | 'child' | 'viewer';

export interface UiContext {
  profile_id: string;
  scopes: string[];
  hidden_panels: string[];
  audience: AudienceBand;
}

export interface UiPreference {
  profile_id: string;
  hidden_panels: string[];
  theme_preference?: string | null;
}

export interface UiPreferenceUpdate {
  hidden_panels: string[];
  theme_preference?: string | null;
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface ApprovalRisk {
  level: RiskLevel;
  label: string;
}

export interface ApprovalItem {
  id: string;
  profile_id: string;
  tool_name: string;
  action_summary: string;
  parameters: Record<string, unknown>;
  risk: ApprovalRisk;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  created_at: string;
  expires_at?: string;
}

export interface ApprovalDecisionRequest {
  decision: 'approve' | 'reject';
  reason?: string;
}

export interface NoteItem {
  id: string;
  title: string;
  content: string;
  tags?: string[];
  created_at: string;
  updated_at: string;
}

export interface ReminderItem {
  id: string;
  profile_id: string;
  title: string;
  rrule?: string;
  due_date?: string;
  completed: boolean;
  snoozed_until?: string;
}

export interface TaskItemData {
  id: string;
  profile_id: string;
  title: string;
  completed: boolean;
  priority?: 'low' | 'medium' | 'high';
  due_date?: string;
}

export interface RoutineItem {
  id: string;
  profile_id: string;
  name: string;
  schedule: string;
  steps: string[];
  enabled: boolean;
}
