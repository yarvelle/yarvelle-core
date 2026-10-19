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
import type { SlotContribution } from '../slots/types.js';
import type { RailItem } from './types.js';

export interface AppRailProps {
  items: RailItem[];
  contributions?: SlotContribution[];
  activeItemId?: string;
  onSelectItem?: (item: RailItem) => void;
  brand?: React.ReactNode;
  footer?: React.ReactNode;
  collapsed?: boolean;
  className?: string;
}

export function AppRail({
  items,
  contributions = [],
  activeItemId,
  onSelectItem,
  brand,
  footer,
  collapsed = false,
  className,
}: AppRailProps) {
  // Merge items with sidebar.item slot contributions
  const allItems: RailItem[] = React.useMemo(() => {
    const list = [...items];
    const slotItems = contributions
      .filter((c) => c.slot === 'sidebar.item')
      .map((c) => ({
        id: c.id,
        label: c.title,
        route: c.route,
        slotContribution: c,
      }));
    list.push(...slotItems);
    return list;
  }, [items, contributions]);

  return (
    <aside
      data-slot="app-rail"
      data-collapsed={collapsed ? 'true' : undefined}
      className={cn(
        'yc-AppRail-root flex flex-col justify-between border-e border-border bg-surface text-fg transition-all duration-normal',
        collapsed ? 'w-16' : 'w-64',
        className
      )}
    >
      <div className="flex flex-col">
        {brand && (
          <div className="flex items-center gap-3 border-b border-border p-4" data-slot="brand">
            {brand}
          </div>
        )}

        <nav className="flex flex-col gap-1 p-2" aria-label="Main Navigation">
          {allItems.map((item) => {
            const isActive = item.active || item.id === activeItemId;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  item.onClick?.();
                  onSelectItem?.(item);
                }}
                data-slot="rail-item"
                data-active={isActive ? 'true' : undefined}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors text-start',
                  collapsed && 'justify-center px-2',
                  isActive
                    ? 'bg-surface-2 text-primary font-semibold shadow-1'
                    : 'text-fg-muted hover:bg-surface-2/60 hover:text-fg'
                )}
                title={collapsed ? item.label : undefined}
              >
                {item.icon && <span className="inline-flex shrink-0">{item.icon}</span>}
                {!collapsed && <span className="truncate flex-1">{item.label}</span>}
                {!collapsed && item.badge !== undefined && (
                  <span className="rounded-full bg-primary-subtle px-1.5 py-0.5 text-[10px] font-bold text-primary">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {footer && (
        <div className="border-t border-border p-3" data-slot="footer">
          {footer}
        </div>
      )}
    </aside>
  );
}
