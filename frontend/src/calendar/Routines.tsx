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
import type { RoutineItem } from './types.js';

export interface RoutinesProps {
  routines: RoutineItem[];
  onToggleActive?: (id: string, active: boolean) => void;
  className?: string;
}

export function Routines({
  routines,
  onToggleActive,
  className,
}: RoutinesProps) {
  return (
    <div
      data-slot="routines"
      className={cn('yc-Routines-root flex flex-col gap-2.5', className)}
    >
      {routines.length === 0 ? (
        <div className="py-6 text-center text-sm text-fg-muted">No active routines configured.</div>
      ) : (
        routines.map((routine) => (
          <div
            key={routine.id}
            data-slot="routine-item"
            className="yc-Routines-item flex items-center justify-between rounded-lg border border-border bg-surface p-3 shadow-1"
          >
            <div className="flex flex-col gap-1">
              <span className="text-sm font-semibold text-fg">{routine.title}</span>
              <div className="flex items-center gap-2 text-xs text-fg-muted">
                <Badge variant="neutral">{routine.frequency}</Badge>
                <span>{routine.timeOfDay}</span>
                {routine.durationMinutes && (
                  <span>({routine.durationMinutes} mins)</span>
                )}
              </div>
            </div>

            <label className="relative inline-flex cursor-pointer items-center">
              <input
                type="checkbox"
                checked={routine.active}
                onChange={(e) => onToggleActive?.(routine.id, e.target.checked)}
                className="sr-only peer"
                aria-label={`Toggle ${routine.title} routine`}
              />
              <div className="h-6 w-11 rounded-full bg-surface-3 peer peer-checked:bg-primary peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all" />
            </label>
          </div>
        ))
      )}
    </div>
  );
}
