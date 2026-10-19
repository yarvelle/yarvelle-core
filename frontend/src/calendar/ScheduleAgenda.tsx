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
import { Badge } from '../primitives/Badge.js';
import type { CalendarEvent } from './types.js';

export interface ScheduleAgendaProps {
  events: CalendarEvent[];
  onSelectEvent?: (event: CalendarEvent) => void;
  className?: string;
}

export function ScheduleAgenda({
  events,
  onSelectEvent,
  className,
}: ScheduleAgendaProps) {
  return (
    <div
      data-slot="schedule-agenda"
      className={cn('yc-ScheduleAgenda-root flex flex-col gap-3', className)}
    >
      {events.length === 0 ? (
        <div className="py-6 text-center text-sm text-fg-muted">No scheduled agenda items.</div>
      ) : (
        events.map((event) => (
          <div
            key={event.id}
            onClick={() => onSelectEvent?.(event)}
            data-slot="agenda-item"
            className={cn(
              'yc-ScheduleAgenda-item flex items-center justify-between rounded-lg border p-3 shadow-1 cursor-pointer transition-colors',
              event.conflict
                ? 'border-danger-border bg-danger-bg/20'
                : 'border-border bg-surface hover:bg-surface-2'
            )}
          >
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold text-fg">{event.title}</span>
              <span className="text-xs text-fg-muted">
                {String(event.start)} {event.location && `• ${event.location}`}
              </span>
            </div>
            {event.conflict && <Badge variant="danger">Conflict</Badge>}
          </div>
        ))
      )}
    </div>
  );
}
