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
import { cn } from '../lib/cn.js';
import { Button } from '../primitives/Button.js';
import { Badge } from '../primitives/Badge.js';
import type { ReminderItem } from './types.js';

export interface RemindersProps {
  reminders: ReminderItem[];
  onComplete?: (id: string, completed: boolean) => void;
  onSnooze?: (id: string, minutes: number) => void;
  className?: string;
}

export function Reminders({
  reminders,
  onComplete,
  onSnooze,
  className,
}: RemindersProps) {
  return (
    <div
      data-slot="reminders"
      className={cn('yc-Reminders-root flex flex-col gap-2', className)}
    >
      {reminders.length === 0 ? (
        <div className="py-6 text-center text-sm text-fg-muted">No reminders pending.</div>
      ) : (
        reminders.map((reminder) => {
          const isDone = reminder.completed;
          return (
            <div
              key={reminder.id}
              data-slot="reminder-item"
              data-completed={isDone ? 'true' : undefined}
              className={cn(
                'yc-Reminders-item flex items-center justify-between rounded-lg border border-border bg-surface p-3 shadow-1 transition-opacity',
                isDone && 'opacity-60'
              )}
            >
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={isDone}
                  onChange={(e) => onComplete?.(reminder.id, e.target.checked)}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                  aria-label={`Mark ${reminder.title} as completed`}
                />
                <div className="flex flex-col">
                  <span
                    className={cn(
                      'text-sm font-medium text-fg',
                      isDone && 'line-through text-fg-muted'
                    )}
                  >
                    {reminder.title}
                  </span>
                  <div className="flex items-center gap-2 text-xs text-fg-muted">
                    <span>Due: {reminder.dueAt}</span>
                    {reminder.rrule && (
                      <Badge variant="neutral" className="text-[10px] px-1 py-0">
                        🔄 {reminder.rrule}
                      </Badge>
                    )}
                    {reminder.snoozedUntil && (
                      <span className="text-warn-fg">Snoozed until {reminder.snoozedUntil}</span>
                    )}
                  </div>
                </div>
              </div>

              {!isDone && onSnooze && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onSnooze(reminder.id, 15)}
                  className="text-xs"
                >
                  Snooze 15m
                </Button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
