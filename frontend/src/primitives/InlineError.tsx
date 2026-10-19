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

export interface InlineErrorProps extends React.HTMLAttributes<HTMLDivElement> {
  message?: React.ReactNode;
  icon?: React.ReactNode;
}

export const InlineError = React.forwardRef<HTMLDivElement, InlineErrorProps>(
  ({ message, icon, children, className, ...props }, ref) => {
    const content = message || children;
    if (!content) return null;

    return (
      <div
        ref={ref}
        role="alert"
        data-slot="inline-error"
        className={cn(
          'yc-InlineError-root flex items-center gap-1.5 text-xs font-medium text-danger-fg',
          className
        )}
        {...props}
      >
        {icon && (
          <span className="yc-InlineError-icon inline-flex shrink-0 items-center" data-slot="icon">
            {icon}
          </span>
        )}
        <span className="yc-InlineError-message" data-slot="message">
          {content}
        </span>
      </div>
    );
  }
);
InlineError.displayName = 'InlineError';
