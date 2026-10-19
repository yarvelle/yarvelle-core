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

export interface ThinkingIndicatorProps {
  label?: string;
  reasoning?: string;
  className?: string;
}

export function ThinkingIndicator({
  label = 'Thinking...',
  reasoning,
  className,
}: ThinkingIndicatorProps) {
  const [open, setOpen] = React.useState(false);

  return (
    <div
      data-slot="thinking-indicator"
      className={cn(
        'yc-ThinkingIndicator-root inline-flex flex-col gap-1 text-xs text-fg-muted',
        className
      )}
    >
      <div className="flex items-center gap-2">
        <span className="flex gap-1 items-center">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-fg-muted" />
          <span className="h-1.5 w-1.5 animate-bounce [animation-delay:0.2s] rounded-full bg-fg-muted" />
          <span className="h-1.5 w-1.5 animate-bounce [animation-delay:0.4s] rounded-full bg-fg-muted" />
        </span>
        <span className="font-medium">{label}</span>
        {reasoning && (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-[11px] underline hover:text-fg"
          >
            {open ? 'Hide details' : 'Show details'}
          </button>
        )}
      </div>

      {open && reasoning && (
        <div className="mt-1 rounded border border-border bg-surface-2 p-2 font-mono text-[11px] text-fg whitespace-pre-wrap">
          {reasoning}
        </div>
      )}
    </div>
  );
}
