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

export type ProfileRole = 'owner' | 'steward' | 'member' | 'viewer';

export interface ProfileMember {
  id: string;
  displayName: string;
  relationship?: string;
  role: ProfileRole;
  avatarUrl?: string;
  colorToken?: string;
  dateOfBirth?: string;
  teenTransitionDate?: string;
  scopes?: string[];
}

export interface ScopePermission {
  domain: string;
  read: boolean;
  write: boolean;
  approve: boolean;
}

export interface ViewerInviteData {
  email: string;
  role: 'viewer';
  scopes: string[];
  expiresInDays: number;
}

export interface ShareBundleData {
  id: string;
  name: string;
  scopes: string[];
  requiresPasscode?: boolean;
  expiresAt?: string;
}
