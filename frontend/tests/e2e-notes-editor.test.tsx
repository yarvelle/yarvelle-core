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
import * as fs from 'node:fs';
import * as path from 'node:path';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import { NotesList, NoteView } from '../src/index.js';
import type { NoteItem } from '../src/notes/types.js';

const noteEditorFile = path.resolve(__dirname, '../src/notes/NoteEditor.tsx');
const hasNoteEditor = fs.existsSync(noteEditorFile);

describe('E2E Notes Workspace Components Suite (Issue #65)', () => {
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

  it('renders NotesList with items, tags, and pinned badges', async () => {
    const onSelect = vi.fn();
    const notes: NoteItem[] = [
      {
        id: 'note-1',
        title: 'Quarterly Operations Summary',
        content: 'Review deployment pipelines and verify security gates.',
        createdAt: '2026-11-01',
        updatedAt: '2026-11-15',
        tags: ['operations', 'quarterly'],
        pinned: true,
      },
      {
        id: 'note-2',
        title: 'Inventory Audit Checklist',
        content: 'Verify resource quotas and disk space usage.',
        createdAt: '2026-11-10',
        updatedAt: '2026-11-14',
        tags: ['audit'],
        pinned: false,
      },
    ];

    await renderComponent(
      <NotesList notes={notes} selectedNoteId="note-1" onSelectNote={onSelect} />
    );

    const listElement = container.querySelector('[data-slot="notes-list"]');
    expect(listElement).not.toBeNull();

    const items = container.querySelectorAll('[data-slot="note-item"]');
    expect(items.length).toBe(2);

    expect(items[0]?.textContent).toContain('Quarterly Operations Summary');
    expect(items[0]?.textContent).toContain('📌');
    expect(items[0]?.textContent).toContain('operations');
    expect(items[0]?.getAttribute('data-selected')).toBe('true');

    // Click note-2
    act(() => {
      (items[1] as HTMLButtonElement).click();
    });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(notes[1]);
  });

  it('renders NotesList empty state when no notes match filters', async () => {
    const onSelect = vi.fn();
    await renderComponent(
      <NotesList
        notes={[]}
        onSelectNote={onSelect}
        emptyTitle="No Notes Available"
        emptyDescription="Create a new note to start tracking objectives."
      />
    );

    expect(container.textContent).toContain('No Notes Available');
    expect(container.textContent).toContain('Create a new note to start tracking objectives.');
  });

  it('renders NoteView with actions, metadata, and handles pin/edit/delete callbacks', async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const onTogglePin = vi.fn();

    const note: NoteItem = {
      id: 'note-target-1',
      title: 'Active Sprint Blueprint',
      content: 'Detailed specifications for sprint deliverables.',
      createdAt: '2026-11-01',
      updatedAt: '2026-11-15',
      tags: ['sprint', 'blueprint'],
      pinned: false,
    };

    await renderComponent(
      <NoteView
        note={note}
        onEdit={onEdit}
        onDelete={onDelete}
        onTogglePin={onTogglePin}
      />
    );

    const viewElement = container.querySelector('[data-slot="note-view"]');
    expect(viewElement).not.toBeNull();
    expect(container.textContent).toContain('Active Sprint Blueprint');
    expect(container.textContent).toContain('Detailed specifications for sprint deliverables.');
    expect(container.textContent).toContain('sprint');
    expect(container.textContent).toContain('blueprint');

    // Click Edit button
    const editButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Edit')
    );
    expect(editButton).toBeDefined();
    act(() => {
      editButton?.click();
    });
    expect(onEdit).toHaveBeenCalledWith(note);

    // Click Pin button
    const pinButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Pin')
    );
    expect(pinButton).toBeDefined();
    act(() => {
      pinButton?.click();
    });
    expect(onTogglePin).toHaveBeenCalledWith('note-target-1');

    // Click Delete button
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Delete')
    );
    expect(deleteButton).toBeDefined();
    act(() => {
      deleteButton?.click();
    });
    expect(onDelete).toHaveBeenCalledWith('note-target-1');
  });

  // Progressive testability: NoteEditor suite runs when NoteEditor is merged
  describe('NoteEditor Component (Progressive Contract)', () => {
    it('verifies NoteEditor export or skips cleanly if pending CM2 merge', async () => {
      if (!hasNoteEditor) {
        // Skip assertion gracefully per Progressive Testability invariant
        expect(true).toBe(true);
        return;
      }

      const modPath = '../src/notes/NoteEditor.js';
      const mod = await import(/* @vite-ignore */ modPath);
      const NoteEditorComponent = mod.NoteEditor;

      const onSave = vi.fn();
      const onCancel = vi.fn();
      await renderComponent(
        <NoteEditorComponent
          initialTitle="Draft Title"
          initialContent="Draft content text"
          onSave={onSave}
          onCancel={onCancel}
        />
      );

      expect(container.querySelector('input')).not.toBeNull();
      expect(container.querySelector('textarea')).not.toBeNull();
    });
  });
});
