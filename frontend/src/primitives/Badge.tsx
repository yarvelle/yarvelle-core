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

export type BadgeVariant =
  | 'default'
  | 'primary'
  | 'neutral'
  | 'info'
  | 'warn'
  | 'danger'
  | 'success'
  | 'outline';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-primary-soft text-primary-soft-fg border-transparent',
  primary: 'bg-primary text-primary-fg border-transparent',
  neutral: 'bg-surface-2 text-fg-muted border-border',
  info: 'bg-info-bg text-info-fg border-info-border',
  warn: 'bg-warn-bg text-warn-fg border-warn-border',
  danger: 'bg-danger-bg text-danger-fg border-danger-border',
  success: 'bg-success-bg text-success-fg border-success-border',
  outline: 'bg-transparent text-fg border-border-strong',
};

export const Badge: React.FC<BadgeProps> = ({
  className,
  variant = 'default',
  children,
  ...props
}) => {
  return (
    <span
      data-slot="badge"
      data-variant={variant}
      className={cn(
        'yc-Badge-root inline-flex items-center rounded-sm border px-2.5 py-0.5 text-xs font-medium transition-colors',
        variantStyles[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
};
Badge.displayName = 'Badge';
