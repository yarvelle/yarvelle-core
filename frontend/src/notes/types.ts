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

export interface NoteItem {
  id: string;
  title: string;
  content: string;
  createdAt: string;
  updatedAt: string;
  type?: string;
  tags?: string[];
  pinned?: boolean;
  authorId?: string;
}

export interface NoteFilterOption {
  id: string;
  label: string;
  count?: number;
}

export interface NoteEditorData {
  title: string;
  content: string;
  type?: string;
  tags?: string[];
  pinned?: boolean;
}

export interface NoteEditorProps {
  initialNote?: Partial<NoteItem> & { type?: string };
  initialTitle?: string;
  initialContent?: string;
  initialType?: string;
  initialTags?: string[];
  initialPinned?: boolean;
  onSave: (noteData: NoteEditorData) => Promise<void> | void;
  onCancel?: () => void;
  className?: string;
  isSaving?: boolean;
}
