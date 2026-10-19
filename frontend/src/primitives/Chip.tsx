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

export type ChipScope = 'health' | 'finance' | 'education' | 'household' | 'default';

export interface ChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  scope?: ChipScope;
  onRemove?: () => void;
  startIcon?: React.ReactNode;
}

const scopeStyles: Record<ChipScope, { default: string; selected: string }> = {
  default: {
    default: 'bg-surface text-fg border-border hover:bg-surface-2',
    selected: 'bg-primary text-primary-fg border-primary',
  },
  health: {
    default: 'bg-scope-health-bg text-scope-health-fg border-transparent hover:opacity-90',
    selected: 'bg-primary text-primary-fg border-primary',
  },
  finance: {
    default: 'bg-scope-finance-bg text-scope-finance-fg border-transparent hover:opacity-90',
    selected: 'bg-primary text-primary-fg border-primary',
  },
  education: {
    default: 'bg-scope-education-bg text-scope-education-fg border-transparent hover:opacity-90',
    selected: 'bg-primary text-primary-fg border-primary',
  },
  household: {
    default: 'bg-scope-household-bg text-scope-household-fg border-transparent hover:opacity-90',
    selected: 'bg-primary text-primary-fg border-primary',
  },
};

export const Chip: React.FC<ChipProps> = ({
  children,
  selected = false,
  scope = 'default',
  onRemove,
  startIcon,
  className,
  onClick,
  disabled = false,
  ...props
}) => {
  return (
    <button
      type="button"
      data-slot="chip"
      data-selected={selected ? 'true' : undefined}
      data-scope={scope}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'yc-Chip-root inline-flex items-center rounded-sm border px-3 py-1 text-xs font-medium transition-colors select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        selected ? scopeStyles[scope].selected : scopeStyles[scope].default,
        className
      )}
      {...props}
    >
      {startIcon && (
        <span className="yc-Chip-icon me-1.5 inline-flex shrink-0 items-center" data-slot="icon">
          {startIcon}
        </span>
      )}
      <span className="yc-Chip-label truncate" data-slot="label">
        {children}
      </span>
      {onRemove && (
        <span
          role="button"
          tabIndex={0}
          aria-label="Remove"
          data-slot="remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="yc-Chip-remove ms-1.5 inline-flex items-center justify-center rounded-full p-0.5 hover:bg-black/10 focus:outline-none"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </span>
      )}
    </button>
  );
};
Chip.displayName = 'Chip';
