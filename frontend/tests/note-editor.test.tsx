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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import { NoteEditor, NotesList } from '../src/index.js';
import type { NoteItem } from '../src/notes/types.js';

describe('NoteEditor Component & NotesList CRUD Controls (Issue #65)', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  const renderComponent = async (element: React.ReactElement) => {
    await act(async () => {
      root.render(element);
    });
  };

  it('renders NoteEditor form with all controls and saves valid note', async () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();

    await renderComponent(
      <NoteEditor
        initialTitle="Initial Briefing"
        initialContent={'# Markdown header\nSome content.'}
        initialType="prep"
        initialTags={['ops', 'review']}
        initialPinned={true}
        onSave={onSave}
        onCancel={onCancel}
      />
    );

    const editor = container.querySelector('[data-slot="note-editor"]');
    expect(editor).not.toBeNull();

    const titleInput = container.querySelector('input[data-slot="title-input"]') as HTMLInputElement;
    expect(titleInput.value).toBe('Initial Briefing');

    const contentInput = container.querySelector('textarea[data-slot="content-input"]') as HTMLTextAreaElement;
    expect(contentInput.value).toContain('Markdown header');
    expect(contentInput.value).toContain('Some content.');

    const typeSelect = container.querySelector('select[data-slot="type-select"]') as HTMLSelectElement;
    expect(typeSelect.value).toBe('prep');

    const pinnedToggle = container.querySelector('input[data-slot="pinned-toggle"]') as HTMLInputElement;
    expect(pinnedToggle.checked).toBe(true);

    // Verify initial tags
    const tagsList = container.querySelector('[data-slot="tags-list"]');
    expect(tagsList?.textContent).toContain('ops');
    expect(tagsList?.textContent).toContain('review');

    // Add a new tag
    const tagInput = container.querySelector('input[data-slot="tag-input"]') as HTMLInputElement;
    const addTagButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Add')
    );
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
      setter?.call(tagInput, 'sprint');
      tagInput.dispatchEvent(new Event('input', { bubbles: true }));
      tagInput.dispatchEvent(new Event('change', { bubbles: true }));
    });
    act(() => {
      addTagButton?.click();
    });
    expect(container.querySelector('[data-slot="tags-list"]')?.textContent).toContain('sprint');

    // Modify title
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
      setter?.call(titleInput, 'Updated Briefing Title');
      titleInput.dispatchEvent(new Event('input', { bubbles: true }));
      titleInput.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // Submit form
    const form = container.querySelector('form') as HTMLFormElement;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({
      title: 'Updated Briefing Title',
      content: '# Markdown header\nSome content.',
      type: 'prep',
      tags: ['ops', 'review', 'sprint'],
      pinned: true,
    });
  });

  it('triggers onCancel when Cancel button is clicked', async () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();

    await renderComponent(
      <NoteEditor onSave={onSave} onCancel={onCancel} />
    );

    const cancelButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Cancel')
    );
    expect(cancelButton).toBeDefined();

    act(() => {
      cancelButton?.click();
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('renders NotesList with New Note button, category tabs, and delete dialog', async () => {
    const onCreateNote = vi.fn();
    const onDeleteNote = vi.fn();
    const onSelectNote = vi.fn();

    const sampleNotes: NoteItem[] = [
      {
        id: 'n-1',
        title: 'General Note',
        content: 'Content 1',
        type: 'general',
        tags: ['alpha'],
        pinned: false,
        createdAt: '2026-11-10',
        updatedAt: '2026-11-15',
      },
      {
        id: 'n-2',
        title: 'Prep Checklist',
        content: 'Content 2',
        type: 'prep',
        tags: ['beta'],
        pinned: true,
        createdAt: '2026-11-11',
        updatedAt: '2026-11-16',
      },
    ];

    await renderComponent(
      <NotesList
        notes={sampleNotes}
        onSelectNote={onSelectNote}
        onCreateNote={onCreateNote}
        onDeleteNote={onDeleteNote}
      />
    );

    // New Note trigger button
    const createBtn = container.querySelector('button[data-slot="create-note-button"]');
    expect(createBtn).not.toBeNull();
    act(() => {
      (createBtn as HTMLButtonElement).click();
    });
    expect(onCreateNote).toHaveBeenCalledTimes(1);

    // Filter by 'Prep' category
    const prepFilterBtn = Array.from(container.querySelectorAll('button[data-slot="category-filter-item"]')).find(
      (b) => b.textContent?.includes('Prep')
    );
    expect(prepFilterBtn).toBeDefined();
    act(() => {
      (prepFilterBtn as HTMLButtonElement).click();
    });

    // Should only show Prep Checklist
    const itemsAfterFilter = container.querySelectorAll('[data-slot="note-item"]');
    expect(itemsAfterFilter.length).toBe(1);
    expect(itemsAfterFilter[0]?.textContent).toContain('Prep Checklist');

    // Click delete on the displayed note item
    const deleteBtn = container.querySelector('button[data-slot="delete-note-button"]');
    expect(deleteBtn).not.toBeNull();
    act(() => {
      (deleteBtn as HTMLButtonElement).click();
    });

    // Dialog appears
    const dialog = document.body.querySelector('[data-slot="delete-confirm-dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('Delete Note');

    // Confirm deletion
    const confirmDeleteBtn = dialog?.querySelector('button[data-slot="confirm-delete-button"]');
    expect(confirmDeleteBtn).not.toBeNull();
    act(() => {
      (confirmDeleteBtn as HTMLButtonElement).click();
    });

    expect(onDeleteNote).toHaveBeenCalledTimes(1);
    expect(onDeleteNote).toHaveBeenCalledWith('n-2');
  });
});
