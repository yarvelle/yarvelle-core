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
import { Chip } from '../primitives/Chip.js';
import type { NoteFilterOption } from './types.js';

export interface RecordSearchProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  selectedFilter: string;
  onFilterChange: (filterId: string) => void;
  filterOptions?: NoteFilterOption[];
  placeholder?: string;
  className?: string;
}

export function RecordSearch({
  searchQuery,
  onSearchChange,
  selectedFilter,
  onFilterChange,
  filterOptions = [
    { id: 'all', label: 'All Records' },
    { id: 'pinned', label: 'Pinned' },
    { id: 'recent', label: 'Recent' },
  ],
  placeholder = 'Search records...',
  className,
}: RecordSearchProps) {
  return (
    <div
      data-slot="record-search"
      className={cn('yc-RecordSearch-root flex flex-col gap-2.5', className)}
    >
      <div className="relative flex items-center">
        <span className="absolute start-3 text-fg-muted text-sm">🔍</span>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-lg border border-border bg-surface-2 py-2 ps-9 pe-3 text-sm text-fg placeholder:text-fg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          data-slot="search-input"
        />
        {searchQuery && (
          <button
            type="button"
            onClick={() => onSearchChange('')}
            className="absolute end-3 text-fg-muted hover:text-fg text-xs"
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      <div
        data-slot="filter-chips"
        className="yc-RecordSearch-chips flex flex-wrap gap-1.5"
      >
        {filterOptions.map((opt) => {
          const isSelected = opt.id === selectedFilter;
          return (
            <Chip
              key={opt.id}
              selected={isSelected}
              onClick={() => onFilterChange(opt.id)}
            >
              {opt.label}
              {opt.count !== undefined && (
                <span className="ms-1.5 text-xs text-fg-muted font-normal">
                  ({opt.count})
                </span>
              )}
            </Chip>
          );
        })}
      </div>
    </div>
  );
}
