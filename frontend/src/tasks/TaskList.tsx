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
import { EmptyState } from '../primitives/EmptyState.js';
import { SegmentedControl } from '../primitives/Segmented.js';
import { TaskItem } from './TaskItem.js';
import type { TaskItemData } from './types.js';

export interface TaskListProps {
  tasks: TaskItemData[];
  onToggleComplete?: (id: string, completed: boolean) => void;
  onAddTask?: (title: string) => void;
  onDeleteTask?: (id: string) => void;
  className?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

export function TaskList({
  tasks,
  onToggleComplete,
  onAddTask,
  onDeleteTask,
  className,
  emptyTitle = 'No tasks',
  emptyDescription = 'You have no tasks in this view.',
}: TaskListProps) {
  const [filter, setFilter] = React.useState<'all' | 'active' | 'completed'>('all');
  const [newTitle, setNewTitle] = React.useState('');

  const filtered = tasks.filter((t) => {
    if (filter === 'active') return !t.completed;
    if (filter === 'completed') return t.completed;
    return true;
  });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newTitle.trim();
    if (!trimmed) return;
    onAddTask?.(trimmed);
    setNewTitle('');
  };

  return (
    <div
      data-slot="task-list"
      className={cn('yc-TaskList-root flex flex-col gap-3', className)}
    >
      <div className="flex items-center justify-between gap-3">
        <SegmentedControl
          size="sm"
          value={filter}
          onChange={(v) => setFilter(v as typeof filter)}
          options={[
            { value: 'all', label: 'All' },
            { value: 'active', label: 'Active' },
            { value: 'completed', label: 'Completed' },
          ]}
        />
        <span className="text-xs text-fg-muted">
          {tasks.filter((t) => !t.completed).length} remaining
        </span>
      </div>

      {onAddTask && (
        <form onSubmit={handleAdd} className="flex gap-2">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Add a new task..."
            className="flex-1 rounded-lg border border-border bg-surface-2 p-2 text-sm text-fg placeholder:text-fg-muted focus:border-primary focus:outline-none"
          />
          <Button type="submit" variant="primary" size="sm">
            Add
          </Button>
        </form>
      )}

      {filtered.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((task) => (
            <TaskItem
              key={task.id}
              task={task}
              onToggleComplete={onToggleComplete}
              onDelete={onDeleteTask}
            />
          ))}
        </div>
      )}
    </div>
  );
}
