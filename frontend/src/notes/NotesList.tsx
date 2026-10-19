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
import { EmptyState } from '../primitives/EmptyState.js';
import type { NoteItem } from './types.js';

export interface NotesListProps {
  notes: NoteItem[];
  selectedNoteId?: string;
  onSelectNote: (note: NoteItem) => void;
  className?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

export function NotesList({
  notes,
  selectedNoteId,
  onSelectNote,
  className,
  emptyTitle = 'No notes found',
  emptyDescription = 'Create a new note or adjust your search filter.',
}: NotesListProps) {
  if (notes.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} className={className} />;
  }

  return (
    <div
      data-slot="notes-list"
      className={cn('yc-NotesList-root flex flex-col gap-2 overflow-y-auto', className)}
    >
      {notes.map((note) => {
        const isSelected = note.id === selectedNoteId;
        return (
          <button
            key={note.id}
            type="button"
            onClick={() => onSelectNote(note)}
            data-slot="note-item"
            data-selected={isSelected ? 'true' : undefined}
            className={cn(
              'yc-NotesList-item flex flex-col text-start rounded-lg border p-3 transition-colors duration-fast shadow-1',
              isSelected
                ? 'border-primary bg-primary-subtle/20'
                : 'border-border bg-surface hover:bg-surface-2'
            )}
          >
            <div className="flex items-center justify-between gap-2 pb-1">
              <span className="font-semibold text-sm text-fg truncate">
                {note.pinned && <span className="me-1 text-primary">📌</span>}
                {note.title || 'Untitled Note'}
              </span>
              <span className="text-[11px] text-fg-muted shrink-0">{note.updatedAt}</span>
            </div>

            <p className="text-xs text-fg-muted line-clamp-2 leading-relaxed">
              {note.content || 'No content'}
            </p>

            {note.tags && note.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {note.tags.map((tag) => (
                  <Badge key={tag} variant="neutral">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
