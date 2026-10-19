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
import type { TaskItemData, TaskPriority } from './types.js';

export interface TaskItemProps {
  task: TaskItemData;
  onToggleComplete?: (id: string, completed: boolean) => void;
  onDelete?: (id: string) => void;
  className?: string;
}

const priorityBadgeVariant: Record<TaskPriority, 'neutral' | 'warn' | 'danger'> = {
  low: 'neutral',
  medium: 'warn',
  high: 'danger',
};

export function TaskItem({
  task,
  onToggleComplete,
  onDelete,
  className,
}: TaskItemProps) {
  const isDone = task.completed;

  return (
    <div
      data-slot="task-item"
      data-completed={isDone ? 'true' : undefined}
      className={cn(
        'yc-TaskItem-root flex items-center justify-between rounded-lg border border-border bg-surface p-3 shadow-1 transition-all',
        isDone && 'opacity-60',
        className
      )}
    >
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={isDone}
          onChange={(e) => onToggleComplete?.(task.id, e.target.checked)}
          className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
          aria-label={`Mark task ${task.title} as ${isDone ? 'incomplete' : 'complete'}`}
        />

        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'text-sm font-medium text-fg',
                isDone && 'line-through text-fg-muted'
              )}
            >
              {task.title}
            </span>
            {task.priority && (
              <Badge variant={priorityBadgeVariant[task.priority]} className="text-[10px] px-1 py-0">
                {task.priority}
              </Badge>
            )}
          </div>

          {(task.description || task.dueAt) && (
            <div className="mt-0.5 flex items-center gap-2 text-xs text-fg-muted">
              {task.description && <span>{task.description}</span>}
              {task.dueAt && <span>Due: {task.dueAt}</span>}
            </div>
          )}
        </div>
      </div>

      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(task.id)}
          className="text-fg-muted hover:text-danger-fg text-xs p-1"
          aria-label={`Delete task ${task.title}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}
