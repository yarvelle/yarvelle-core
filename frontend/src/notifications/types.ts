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

export type NotificationLevel = 'info' | 'warn' | 'danger' | 'success';

export interface NotificationMessage {
  id: string;
  title: string;
  description?: string;
  timestamp: string;
  read: boolean;
  level?: NotificationLevel;
  actionUrl?: string;
}
