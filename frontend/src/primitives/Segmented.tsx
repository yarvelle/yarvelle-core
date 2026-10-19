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

export interface SegmentedOption {
  value: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps {
  options: SegmentedOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  className?: string;
  size?: 'sm' | 'md';
}

export function SegmentedControl({
  options,
  value: controlledValue,
  defaultValue,
  onChange,
  className,
  size = 'md',
}: SegmentedControlProps) {
  const [uncontrolledValue, setUncontrolledValue] = React.useState(
    defaultValue || (options.length > 0 ? options[0].value : '')
  );
  const isControlled = controlledValue !== undefined;
  const activeValue = isControlled ? controlledValue : uncontrolledValue;

  const handleClick = (optValue: string) => {
    if (!isControlled) {
      setUncontrolledValue(optValue);
    }
    onChange?.(optValue);
  };

  const sizeClasses = size === 'sm' ? 'h-8 p-0.5 text-xs' : 'min-h-[44px] h-10 p-1 text-sm';

  return (
    <div
      role="radiogroup"
      data-slot="segmented-control"
      data-size={size}
      className={cn(
        'yc-Segmented-root inline-flex items-center rounded-lg bg-surface-2 text-fg-muted border border-border select-none',
        sizeClasses,
        className
      )}
    >
      {options.map((opt) => {
        const isSelected = opt.value === activeValue;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={isSelected}
            disabled={opt.disabled}
            data-slot="item"
            data-state={isSelected ? 'checked' : 'unchecked'}
            onClick={() => handleClick(opt.value)}
            className={cn(
              'yc-Segmented-item inline-flex h-full items-center justify-center gap-1.5 rounded-md px-3 font-medium transition-all duration-fast',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus',
              'disabled:pointer-events-none disabled:opacity-50',
              isSelected
                ? 'bg-surface text-fg shadow-1'
                : 'text-fg-muted hover:text-fg hover:bg-surface-3'
            )}
          >
            {opt.icon && (
              <span className="yc-Segmented-icon inline-flex shrink-0 items-center" data-slot="icon">
                {opt.icon}
              </span>
            )}
            <span className="yc-Segmented-label truncate" data-slot="label">
              {opt.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
