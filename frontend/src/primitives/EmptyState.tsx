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

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ icon, title, description, action, className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        data-slot="empty-state"
        className={cn(
          'yc-EmptyState-root flex flex-col items-center justify-center p-8 text-center',
          className
        )}
        {...props}
      >
        {icon && (
          <div
            className="yc-EmptyState-icon mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-fg-muted"
            data-slot="icon"
          >
            {icon}
          </div>
        )}
        <h3 className="yc-EmptyState-title text-base font-medium text-fg" data-slot="title">
          {title}
        </h3>
        {description && (
          <p
            className="yc-EmptyState-description mt-1.5 max-w-sm text-sm text-fg-muted"
            data-slot="description"
          >
            {description}
          </p>
        )}
        {action && (
          <div className="yc-EmptyState-action mt-5" data-slot="action">
            {action}
          </div>
        )}
      </div>
    );
  }
);
EmptyState.displayName = 'EmptyState';
