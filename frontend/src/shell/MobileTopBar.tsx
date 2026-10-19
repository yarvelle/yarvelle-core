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

export interface MobileTopBarProps {
  title?: React.ReactNode;
  startSlot?: React.ReactNode;
  endSlot?: React.ReactNode;
  leftSlot?: React.ReactNode;
  rightSlot?: React.ReactNode;
  className?: string;
}

export function MobileTopBar({
  title,
  startSlot,
  endSlot,
  leftSlot,
  rightSlot,
  className,
}: MobileTopBarProps) {
  const leading = startSlot || leftSlot;
  const trailing = endSlot || rightSlot;

  return (
    <header
      data-slot="mobile-top-bar"
      className={cn(
        'yc-MobileTopBar-root flex items-center justify-between border-b border-border bg-surface px-4 py-2.5 text-fg md:hidden z-30 sticky top-0',
        className
      )}
    >
      <div className="flex items-center gap-2" data-slot="start-slot">
        {leading}
      </div>

      {title && (
        <h1 className="text-base font-bold text-fg truncate text-center flex-1 px-2" data-slot="title">
          {title}
        </h1>
      )}

      <div className="flex items-center gap-2" data-slot="end-slot">
        {trailing}
      </div>
    </header>
  );
}
