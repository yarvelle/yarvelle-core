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

export type CalendarViewMode = 'month' | 'week' | 'agenda';

export interface CalendarEvent {
  id: string;
  title: string;
  start: Date | string;
  end: Date | string;
  allDay?: boolean;
  location?: string;
  conflict?: boolean;
  recurrenceRule?: string;
  description?: string;
}

export interface ReminderItem {
  id: string;
  title: string;
  dueAt: string;
  rrule?: string;
  snoozedUntil?: string;
  completed?: boolean;
  category?: string;
}

export interface RoutineItem {
  id: string;
  title: string;
  frequency: 'daily' | 'weekdays' | 'weekends' | 'weekly';
  timeOfDay: string;
  durationMinutes?: number;
  active: boolean;
}

export interface TimelineEvent {
  id: string;
  title: string;
  timestamp: string;
  description?: string;
  status?: 'info' | 'success' | 'warn' | 'danger';
  icon?: string;
}
