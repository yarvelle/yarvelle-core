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
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '../primitives/Sheet.js';
import { ToolTraceCard } from './ToolTraceCard.js';
import type { ToolCallTrace } from './types.js';

export interface ActivityLogDrawerProps {
  traces: ToolCallTrace[];
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  trigger?: React.ReactNode;
}

export function ActivityLogDrawer({
  traces,
  open,
  onOpenChange,
  trigger,
}: ActivityLogDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {trigger && <SheetTrigger asChild>{trigger}</SheetTrigger>}
      <SheetContent side="end" className="yc-ActivityLogDrawer-content flex flex-col gap-4">
        <SheetHeader>
          <SheetTitle>Activity Log</SheetTitle>
          <SheetDescription>
            Audit log of agent execution traces and tool calls.
          </SheetDescription>
        </SheetHeader>

        <div
          data-slot="activity-log-drawer"
          className="yc-ActivityLogDrawer-root flex-1 overflow-y-auto space-y-2 pe-1"
        >
          {traces.length === 0 ? (
            <div className="text-center text-xs text-fg-muted py-8">
              No activity recorded for this session.
            </div>
          ) : (
            traces.map((trace) => (
              <ToolTraceCard key={trace.id} trace={trace} defaultExpanded={false} />
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
