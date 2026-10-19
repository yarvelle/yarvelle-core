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
import type { ExecutionPlanStep } from './types.js';

export interface ExecutionPlanCardProps {
  steps: ExecutionPlanStep[];
  className?: string;
  title?: string;
}

export function ExecutionPlanCard({
  steps,
  className,
  title = 'Execution Plan',
}: ExecutionPlanCardProps) {
  if (!steps || steps.length === 0) return null;

  return (
    <div
      data-slot="execution-plan-card"
      className={cn(
        'yc-ExecutionPlanCard-root my-2 rounded-lg border border-border bg-surface p-3 text-xs shadow-1',
        className
      )}
    >
      <div className="font-semibold text-fg pb-2 flex items-center justify-between">
        <span>{title}</span>
        <span className="text-fg-muted">
          {steps.filter((s) => s.status === 'completed').length}/{steps.length}
        </span>
      </div>
      <div className="space-y-1.5">
        {steps.map((step, idx) => {
          const isDone = step.status === 'completed';
          const isRunning = step.status === 'running';
          const isFailed = step.status === 'failed';

          return (
            <div
              key={step.id || idx}
              data-slot="step"
              data-status={step.status}
              className="yc-ExecutionPlanCard-step flex items-start gap-2"
            >
              <span
                className={cn(
                  'mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                  isDone
                    ? 'bg-success-fg text-white'
                    : isRunning
                    ? 'animate-spin border-2 border-primary border-t-transparent'
                    : isFailed
                    ? 'bg-danger-fg text-white'
                    : 'bg-surface-3 text-fg-muted'
                )}
              >
                {isDone ? '✓' : isFailed ? '✕' : isRunning ? '' : idx + 1}
              </span>
              <span
                className={cn(
                  'flex-1 text-fg',
                  isDone && 'line-through text-fg-muted',
                  isRunning && 'font-medium text-primary'
                )}
              >
                {step.description}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
