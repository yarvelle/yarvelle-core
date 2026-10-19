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

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-primary hover:bg-primary-hover active:bg-primary-hover text-primary-fg border border-transparent shadow-1',
  secondary:
    'bg-surface hover:bg-surface-2 active:bg-surface-3 text-fg border border-border-strong shadow-1',
  ghost:
    'bg-transparent hover:bg-surface-2 active:bg-surface-3 text-fg-muted hover:text-fg border border-transparent',
  outline:
    'bg-transparent hover:bg-surface-2 active:bg-surface-3 text-fg border border-border-strong',
  danger:
    'bg-danger-bg hover:bg-danger-fg text-danger-fg hover:text-white border border-danger-border',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-[34px] px-3 text-sm rounded-md relative before:absolute before:-inset-y-1.5 before:inset-x-0 before:content-[\'\']',
  md: 'min-h-[44px] h-10 px-4 text-sm rounded-md',
  lg: 'min-h-[48px] h-12 px-5 text-base rounded-md',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      disabled = false,
      leftIcon,
      rightIcon,
      children,
      className,
      type = 'button',
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        data-slot="button"
        data-variant={variant}
        data-size={size}
        data-loading={loading ? 'true' : undefined}
        className={cn(
          'yc-Button-root inline-flex items-center justify-center font-medium select-none',
          'transition-colors duration-fast ease-ui',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2',
          'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        {...props}
      >
        {loading ? (
          <span
            className="yc-Button-spinner me-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
            data-slot="spinner"
            role="status"
            aria-label="Loading"
          />
        ) : leftIcon ? (
          <span className="yc-Button-icon yc-Button-icon-start me-2 inline-flex shrink-0 items-center" data-slot="icon-start">
            {leftIcon}
          </span>
        ) : null}

        <span className="yc-Button-label truncate" data-slot="label">
          {children}
        </span>

        {!loading && rightIcon ? (
          <span className="yc-Button-icon yc-Button-icon-end ms-2 inline-flex shrink-0 items-center" data-slot="icon-end">
            {rightIcon}
          </span>
        ) : null}
      </button>
    );
  }
);

Button.displayName = 'Button';
