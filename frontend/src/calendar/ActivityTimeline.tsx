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
import type { TimelineEvent } from './types.js';

export interface ActivityTimelineProps {
  events: TimelineEvent[];
  className?: string;
}

const statusColors: Record<NonNullable<TimelineEvent['status']>, string> = {
  info: 'bg-info-fg',
  success: 'bg-success-fg',
  warn: 'bg-warn-fg',
  danger: 'bg-danger-fg',
};

export function ActivityTimeline({ events, className }: ActivityTimelineProps) {
  return (
    <div
      data-slot="activity-timeline"
      className={cn('yc-ActivityTimeline-root flex flex-col', className)}
    >
      {events.length === 0 ? (
        <div className="py-6 text-center text-sm text-fg-muted">No timeline activities.</div>
      ) : (
        <div className="relative border-s border-border ms-3.5 space-y-6 my-2">
          {events.map((ev) => (
            <div
              key={ev.id}
              data-slot="timeline-item"
              className="yc-ActivityTimeline-item relative ps-6"
            >
              {/* Dot */}
              <span
                className={cn(
                  'absolute -start-1.5 top-1 h-3 w-3 rounded-full border-2 border-surface',
                  statusColors[ev.status || 'info']
                )}
              />

              <div className="flex flex-col">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-fg">{ev.title}</span>
                  <span className="text-xs text-fg-muted">{ev.timestamp}</span>
                </div>
                {ev.description && (
                  <p className="mt-1 text-xs text-fg-muted leading-relaxed">
                    {ev.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
