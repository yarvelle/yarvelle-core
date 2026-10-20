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

import type {
  ApprovalDecisionRequest,
  ApprovalItem,
  NoteItem,
  ReminderItem,
  RoutineItem,
  TaskItemData,
  UiContext,
  UiPreference,
  UiPreferenceUpdate,
} from './types.js';

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = '/api/v1') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
    const headers = new Headers(options.headers || {});
    if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      let detail = `HTTP ${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch {
        // Fallback to text status
      }
      throw new Error(detail);
    }
    return response.json() as Promise<T>;
  }

  async getUiContext(profileId?: string): Promise<UiContext> {
    const q = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
    return this.request<UiContext>(`/me/ui-context${q}`);
  }

  async getUiPrefs(profileId: string): Promise<UiPreference> {
    return this.request<UiPreference>(`/me/profiles/${encodeURIComponent(profileId)}/ui-prefs`);
  }

  async updateUiPrefs(profileId: string, prefs: UiPreferenceUpdate): Promise<UiPreference> {
    return this.request<UiPreference>(`/me/profiles/${encodeURIComponent(profileId)}/ui-prefs`, {
      method: 'PUT',
      body: JSON.stringify(prefs),
    });
  }

  async decideApproval(approvalId: string, decision: 'approve' | 'reject', reason?: string): Promise<ApprovalItem> {
    const body: ApprovalDecisionRequest = { decision, reason };
    return this.request<ApprovalItem>(`/approvals/${encodeURIComponent(approvalId)}/decide`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async resumeChat(threadId: string, payload: Record<string, unknown> = {}): Promise<{ status: string }> {
    return this.request<{ status: string }>(`/chat/resume`, {
      method: 'POST',
      body: JSON.stringify({ thread_id: threadId, ...payload }),
    });
  }
}

export const defaultApiClient = new ApiClient();
