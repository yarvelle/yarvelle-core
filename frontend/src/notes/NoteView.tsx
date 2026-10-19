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
import type { NoteItem } from './types.js';

export interface NoteViewProps {
  note: NoteItem;
  onEdit?: (note: NoteItem) => void;
  onDelete?: (noteId: string) => void;
  onTogglePin?: (noteId: string) => void;
  className?: string;
}

export function NoteView({
  note,
  onEdit,
  onDelete,
  onTogglePin,
  className,
}: NoteViewProps) {
  return (
    <div
      data-slot="note-view"
      className={cn(
        'yc-NoteView-root flex flex-col h-full rounded-lg border border-border bg-surface p-6 shadow-1',
        className
      )}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border pb-4">
        <div>
          <h2 className="yc-NoteView-title text-xl font-bold text-fg flex items-center gap-2">
            {note.pinned && <span className="text-primary text-base">📌</span>}
            {note.title || 'Untitled Note'}
          </h2>
          <div className="mt-1 flex items-center gap-3 text-xs text-fg-muted">
            <span>Updated {note.updatedAt}</span>
            <span>Created {note.createdAt}</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onTogglePin && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onTogglePin(note.id)}
              aria-label={note.pinned ? 'Unpin note' : 'Pin note'}
            >
              {note.pinned ? 'Unpin' : 'Pin'}
            </Button>
          )}
          {onEdit && (
            <Button size="sm" variant="secondary" onClick={() => onEdit(note)}>
              Edit
            </Button>
          )}
          {onDelete && (
            <Button size="sm" variant="danger" onClick={() => onDelete(note.id)}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {note.tags && note.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 pb-2">
          {note.tags.map((tag) => (
            <Badge key={tag} variant="neutral">
              {tag}
            </Badge>
          ))}
        </div>
      )}

      <div
        data-slot="note-content"
        className="yc-NoteView-content mt-4 flex-1 overflow-y-auto text-sm text-fg leading-relaxed whitespace-pre-wrap"
      >
        {note.content}
      </div>
    </div>
  );
}
