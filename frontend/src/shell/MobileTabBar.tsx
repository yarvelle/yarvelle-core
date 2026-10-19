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
import type { RailItem } from './types.js';

export interface MobileTabBarProps {
  items: RailItem[];
  activeItemId?: string;
  onSelectItem?: (item: RailItem) => void;
  className?: string;
}

export function MobileTabBar({
  items,
  activeItemId,
  onSelectItem,
  className,
}: MobileTabBarProps) {
  return (
    <nav
      data-slot="mobile-tab-bar"
      className={cn(
        'yc-MobileTabBar-root fixed bottom-0 inset-x-0 z-30 flex items-center justify-around border-t border-border bg-surface px-2 py-1 md:hidden',
        className
      )}
      aria-label="Mobile Navigation"
    >
      {items.map((item) => {
        const isActive = item.active || item.id === activeItemId;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              item.onClick?.();
              onSelectItem?.(item);
            }}
            data-slot="tab-item"
            data-active={isActive ? 'true' : undefined}
            className={cn(
              'flex flex-col items-center justify-center flex-1 py-1.5 px-1 text-[11px] font-medium transition-colors min-h-[44px]',
              isActive ? 'text-primary font-bold' : 'text-fg-muted hover:text-fg'
            )}
          >
            {item.icon && <span className="text-lg leading-none mb-0.5">{item.icon}</span>}
            <span className="truncate max-w-[64px]">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
