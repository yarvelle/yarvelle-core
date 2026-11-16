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
import type { NoteEditorData, NoteEditorProps } from './types.js';

const NOTE_TYPES = [
  { value: 'general', label: 'General' },
  { value: 'scratchpad', label: 'Scratchpad' },
  { value: 'prep', label: 'Preparation' },
  { value: 'summary', label: 'Summary' },
];

export function NoteEditor({
  initialNote,
  initialTitle,
  initialContent,
  initialType,
  initialTags,
  initialPinned,
  onSave,
  onCancel,
  className,
  isSaving = false,
}: NoteEditorProps) {
  const [title, setTitle] = React.useState<string>(
    initialTitle ?? initialNote?.title ?? ''
  );
  const [content, setContent] = React.useState<string>(
    initialContent ?? initialNote?.content ?? ''
  );
  const [type, setType] = React.useState<string>(
    initialType ?? initialNote?.type ?? 'general'
  );
  const [tags, setTags] = React.useState<string[]>(
    initialTags ?? initialNote?.tags ?? []
  );
  const [pinned, setPinned] = React.useState<boolean>(
    initialPinned ?? initialNote?.pinned ?? false
  );
  const [tagInput, setTagInput] = React.useState<string>('');
  const [savingState, setSavingState] = React.useState<boolean>(false);
  const [error, setError] = React.useState<string | null>(null);

  const effectiveSaving = isSaving || savingState;

  const handleAddTag = () => {
    const clean = tagInput.trim();
    if (clean && !tags.includes(clean)) {
      setTags([...tags, clean]);
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  const handleKeyDownTag = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      handleAddTag();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError('Title is required');
      return;
    }
    setError(null);
    setSavingState(true);
    try {
      const data: NoteEditorData = {
        title: title.trim(),
        content,
        type,
        tags,
        pinned,
      };
      await onSave(data);
    } catch (err: any) {
      setError(err?.message || 'Failed to save note');
    } finally {
      setSavingState(false);
    }
  };

  return (
    <form
      data-slot="note-editor"
      onSubmit={handleSubmit}
      className={cn(
        'yc-NoteEditor-root flex flex-col gap-4 rounded-xl border border-border bg-surface p-6 shadow-1',
        className
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border pb-3">
        <h3 className="text-base font-bold text-fg">
          {initialNote?.id ? 'Edit Note' : 'Create Note'}
        </h3>
        <label className="flex items-center gap-2 cursor-pointer select-none text-xs font-medium text-fg">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(e) => setPinned(e.target.checked)}
            className="rounded border-border text-primary focus:ring-primary"
            data-slot="pinned-toggle"
          />
          <span>Pin to top 📌</span>
        </label>
      </div>

      {error && (
        <div
          data-slot="editor-error"
          className="rounded-lg bg-danger-bg p-3 text-xs text-danger-fg"
        >
          {error}
        </div>
      )}

      {/* Title input */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="note-title" className="text-xs font-semibold text-fg">
          Title <span className="text-danger">*</span>
        </label>
        <input
          id="note-title"
          data-slot="title-input"
          type="text"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            if (error) setError(null);
          }}
          placeholder="Note title..."
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          required
        />
      </div>

      {/* Category/Type Select */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="note-type" className="text-xs font-semibold text-fg">
          Category
        </label>
        <select
          id="note-type"
          data-slot="type-select"
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {NOTE_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {/* Tags Input */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="note-tags" className="text-xs font-semibold text-fg">
          Tags
        </label>
        <div className="flex gap-2">
          <input
            id="note-tags"
            data-slot="tag-input"
            type="text"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={handleKeyDownTag}
            placeholder="Add tag and press Enter..."
            className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleAddTag}
            disabled={!tagInput.trim()}
          >
            Add
          </Button>
        </div>
        {tags.length > 0 && (
          <div data-slot="tags-list" className="flex flex-wrap gap-1.5 mt-1">
            {tags.map((tag) => (
              <Badge key={tag} variant="neutral" className="flex items-center gap-1 ps-2 pe-1 py-0.5">
                <span>{tag}</span>
                <button
                  type="button"
                  onClick={() => handleRemoveTag(tag)}
                  className="cursor-pointer text-fg-muted hover:text-fg"
                  aria-label={`Remove tag ${tag}`}
                >
                  ×
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Content textarea */}
      <div className="flex flex-col gap-1.5 flex-1">
        <label htmlFor="note-content" className="text-xs font-semibold text-fg">
          Content (Markdown)
        </label>
        <textarea
          id="note-content"
          data-slot="content-input"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Write your note content here..."
          rows={8}
          className="w-full rounded-lg border border-border bg-surface p-3 text-sm text-fg font-mono placeholder:text-fg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary resize-y"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            disabled={effectiveSaving}
          >
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          variant="primary"
          disabled={effectiveSaving || !title.trim()}
          data-slot="save-button"
        >
          {effectiveSaving ? 'Saving...' : 'Save Note'}
        </Button>
      </div>
    </form>
  );
}
