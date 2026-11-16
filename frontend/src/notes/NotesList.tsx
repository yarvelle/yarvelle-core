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
import { Button } from '../primitives/Button.js';
import { EmptyState } from '../primitives/EmptyState.js';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../primitives/Dialog.js';
import type { NoteItem } from './types.js';

export interface NotesListProps {
  notes: NoteItem[];
  selectedNoteId?: string;
  onSelectNote: (note: NoteItem) => void;
  onCreateNote?: () => void;
  onDeleteNote?: (noteId: string) => void;
  className?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  categoryFilter?: string;
  onCategoryFilterChange?: (category: string) => void;
  tagFilter?: string | null;
  onTagFilterChange?: (tag: string | null) => void;
}

const CATEGORIES = [
  { value: 'all', label: 'All' },
  { value: 'general', label: 'General' },
  { value: 'scratchpad', label: 'Scratchpad' },
  { value: 'prep', label: 'Prep' },
  { value: 'summary', label: 'Summary' },
];

export function NotesList({
  notes,
  selectedNoteId,
  onSelectNote,
  onCreateNote,
  onDeleteNote,
  className,
  emptyTitle = 'No notes found',
  emptyDescription = 'Create a new note or adjust your search filter.',
  categoryFilter: controlledCategory,
  onCategoryFilterChange,
  tagFilter: controlledTag,
  onTagFilterChange,
}: NotesListProps) {
  const [internalCategory, setInternalCategory] = React.useState<string>('all');
  const [internalTag, setInternalTag] = React.useState<string | null>(null);
  const [deletingNote, setDeletingNote] = React.useState<NoteItem | null>(null);

  const activeCategory = controlledCategory ?? internalCategory;
  const setCategory = (cat: string) => {
    setInternalCategory(cat);
    onCategoryFilterChange?.(cat);
  };

  const activeTag = controlledTag !== undefined ? controlledTag : internalTag;
  const setTag = (t: string | null) => {
    setInternalTag(t);
    onTagFilterChange?.(t);
  };

  // Collect all unique tags across notes
  const allTags = React.useMemo(() => {
    const set = new Set<string>();
    notes.forEach((n) => {
      n.tags?.forEach((t) => set.add(t));
    });
    return Array.from(set);
  }, [notes]);

  // Filter notes based on active category and tag
  const filteredNotes = React.useMemo(() => {
    return notes.filter((note) => {
      if (activeCategory !== 'all' && note.type && note.type !== activeCategory) {
        return false;
      }
      if (activeTag && (!note.tags || !note.tags.includes(activeTag))) {
        return false;
      }
      return true;
    });
  }, [notes, activeCategory, activeTag]);

  return (
    <div
      data-slot="notes-list-container"
      className={cn('yc-NotesList-container flex flex-col gap-3', className)}
    >
      {/* Header with New Note button and filters */}
      {(onCreateNote || allTags.length > 0 || notes.length > 0) && (
        <div className="flex flex-col gap-2 border-b border-border pb-3">
          <div className="flex items-center justify-between gap-2">
            {/* Category Filter Selector */}
            <div data-slot="category-filters" className="flex flex-wrap items-center gap-1">
              {CATEGORIES.map((cat) => {
                const isActive = activeCategory === cat.value;
                return (
                  <button
                    key={cat.value}
                    type="button"
                    onClick={() => setCategory(cat.value)}
                    data-slot="category-filter-item"
                    data-active={isActive ? 'true' : undefined}
                    className={cn(
                      'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                      isActive
                        ? 'bg-primary text-primary-fg font-semibold'
                        : 'bg-surface-2 text-fg-muted hover:bg-surface-3 hover:text-fg'
                    )}
                  >
                    {cat.label}
                  </button>
                );
              })}
            </div>

            {/* Create Note Trigger */}
            {onCreateNote && (
              <Button
                size="sm"
                variant="primary"
                onClick={onCreateNote}
                data-slot="create-note-button"
              >
                + New Note
              </Button>
            )}
          </div>

          {/* Tag Filter Chips */}
          {allTags.length > 0 && (
            <div data-slot="tag-filters" className="flex flex-wrap items-center gap-1.5 pt-1">
              <span className="text-[11px] font-semibold text-fg-muted me-1">Tags:</span>
              {allTags.map((tag) => {
                const isTagActive = activeTag === tag;
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => setTag(isTagActive ? null : tag)}
                    data-slot="tag-filter-chip"
                    data-active={isTagActive ? 'true' : undefined}
                    className={cn(
                      'cursor-pointer rounded-full px-2 py-0.5 text-[11px] transition-colors',
                      isTagActive
                        ? 'bg-primary text-primary-fg font-semibold'
                        : 'bg-surface-2 text-fg-muted hover:bg-surface-3 hover:text-fg'
                    )}
                  >
                    #{tag}
                  </button>
                );
              })}
              {activeTag && (
                <button
                  type="button"
                  onClick={() => setTag(null)}
                  className="text-[11px] text-fg-muted hover:text-fg underline ps-1"
                >
                  Clear tag
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Main List */}
      {notes.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      ) : filteredNotes.length === 0 ? (
        <div data-slot="no-filter-matches" className="py-8 text-center text-sm text-fg-muted">
          No notes match the selected filters.
        </div>
      ) : (
        <div
          data-slot="notes-list"
          className="yc-NotesList-root flex flex-col gap-2 overflow-y-auto"
        >
          {filteredNotes.map((note) => {
            const isSelected = note.id === selectedNoteId;
            return (
              <div
                key={note.id}
                onClick={() => onSelectNote(note)}
                data-slot="note-item"
                data-selected={isSelected ? 'true' : undefined}
                className={cn(
                  'yc-NotesList-item group flex flex-col text-start rounded-lg border p-3 transition-colors duration-fast shadow-1 cursor-pointer',
                  isSelected
                    ? 'border-primary bg-primary-soft/20'
                    : 'border-border bg-surface hover:bg-surface-2'
                )}
              >
                <div className="flex items-center justify-between gap-2 pb-1">
                  <span className="font-semibold text-sm text-fg truncate flex items-center gap-1">
                    {note.pinned && <span className="text-primary">📌</span>}
                    {note.title || 'Untitled Note'}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[11px] text-fg-muted">{note.updatedAt}</span>
                    {onDeleteNote && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeletingNote(note);
                        }}
                        data-slot="delete-note-button"
                        aria-label={`Delete note ${note.title || note.id}`}
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-xs text-danger hover:text-danger-fg hover:bg-danger-bg rounded px-1.5 py-0.5"
                      >
                        Delete
                      </button>
                    )}
                  </div>
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
              </div>
            );
          })}
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={!!deletingNote}
        onOpenChange={(open) => {
          if (!open) setDeletingNote(null);
        }}
      >
        <DialogContent data-slot="delete-confirm-dialog">
          <DialogHeader>
            <DialogTitle>Delete Note</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete &ldquo;{deletingNote?.title || 'this note'}&rdquo;?
              This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDeletingNote(null)}
              data-slot="cancel-delete-button"
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              data-slot="confirm-delete-button"
              onClick={() => {
                if (deletingNote) {
                  onDeleteNote?.(deletingNote.id);
                  setDeletingNote(null);
                }
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
