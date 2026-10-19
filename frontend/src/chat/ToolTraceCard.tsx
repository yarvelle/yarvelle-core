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
import type { ToolCallTrace } from './types.js';

export interface ToolTraceCardProps {
  trace: ToolCallTrace;
  className?: string;
  defaultExpanded?: boolean;
}

export function ToolTraceCard({
  trace,
  className,
  defaultExpanded = false,
}: ToolTraceCardProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded);

  const statusVariant: Record<ToolCallTrace['status'], 'info' | 'success' | 'danger'> = {
    running: 'info',
    success: 'success',
    error: 'danger',
  };

  return (
    <div
      data-slot="tool-trace-card"
      className={cn(
        'yc-ToolTraceCard-root my-1.5 rounded-lg border border-border bg-surface text-fg shadow-1 text-xs',
        className
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        data-slot="header"
        className="yc-ToolTraceCard-header flex w-full items-center justify-between p-2.5 text-start font-mono transition-colors hover:bg-surface-2"
      >
        <div className="flex items-center gap-2">
          <span className="font-semibold text-fg">{trace.toolName}</span>
          <Badge variant={statusVariant[trace.status]}>{trace.status}</Badge>
          {trace.durationMs !== undefined && (
            <span className="text-fg-muted">({trace.durationMs}ms)</span>
          )}
        </div>
        <span className="text-fg-muted">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div data-slot="details" className="yc-ToolTraceCard-details border-t border-border p-2.5 font-mono space-y-2">
          {trace.input !== undefined && (
            <div>
              <div className="text-fg-muted text-[10px] uppercase font-semibold">Input</div>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-2 p-2 text-fg">
                {typeof trace.input === 'string'
                  ? trace.input
                  : JSON.stringify(trace.input, null, 2)}
              </pre>
            </div>
          )}
          {trace.output !== undefined && (
            <div>
              <div className="text-fg-muted text-[10px] uppercase font-semibold">Output</div>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-2 p-2 text-fg">
                {typeof trace.output === 'string'
                  ? trace.output
                  : JSON.stringify(trace.output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
