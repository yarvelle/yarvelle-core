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

export interface MermaidDiagramProps {
  chart: string;
  className?: string;
}

export function MermaidDiagram({ chart, className }: MermaidDiagramProps) {
  const [showSource, setShowSource] = React.useState(false);

  return (
    <div
      data-slot="mermaid-diagram"
      className={cn(
        'yc-MermaidDiagram-root my-3 rounded-lg border border-border bg-surface p-3 text-xs shadow-1',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-2 mb-2 text-fg-muted font-mono">
        <span className="font-semibold text-fg">Diagram</span>
        <button
          type="button"
          onClick={() => setShowSource(!showSource)}
          className="text-[11px] underline hover:text-fg"
        >
          {showSource ? 'View rendering' : 'View syntax'}
        </button>
      </div>

      {showSource ? (
        <pre className="overflow-x-auto rounded bg-surface-2 p-3 font-mono text-fg">
          <code>{chart}</code>
        </pre>
      ) : (
        <div
          data-slot="diagram-viewport"
          className="yc-MermaidDiagram-viewport flex items-center justify-center p-4 bg-surface-2 rounded overflow-x-auto"
        >
          {/* Render diagram text representation / SVG placeholder */}
          <pre className="font-mono text-xs text-fg leading-relaxed">{chart}</pre>
        </div>
      )}
    </div>
  );
}
