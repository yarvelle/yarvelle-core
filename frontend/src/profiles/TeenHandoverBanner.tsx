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

export interface TeenHandoverBannerProps {
  memberName: string;
  handoverDate: string;
  onInitiateHandover?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function TeenHandoverBanner({
  memberName,
  handoverDate,
  onInitiateHandover,
  onDismiss,
  className,
}: TeenHandoverBannerProps) {
  return (
    <div
      data-slot="teen-handover-banner"
      className={cn(
        'yc-TeenHandoverBanner-root flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-xl border border-warn-border bg-warn-bg/30 p-4 text-xs text-fg shadow-1',
        className
      )}
    >
      <div className="flex items-start gap-3">
        <span className="text-warn-fg text-lg leading-none">⚠️</span>
        <div>
          <h4 className="font-semibold text-fg">Privacy & Age-of-Majority Transition</h4>
          <p className="mt-0.5 text-fg-muted">
            <span className="font-medium text-fg">{memberName}</span> reaches transition age on{' '}
            <span className="font-medium text-fg">{handoverDate}</span>. Account stewardship and record privacy settings should be reviewed.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {onDismiss && (
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
        {onInitiateHandover && (
          <Button size="sm" variant="outline" onClick={onInitiateHandover}>
            Review Privacy
          </Button>
        )}
      </div>
    </div>
  );
}
