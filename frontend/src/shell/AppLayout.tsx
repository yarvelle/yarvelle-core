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
import { AppRail } from './AppRail.js';
import { MobileTopBar } from './MobileTopBar.js';
import { MobileTabBar } from './MobileTabBar.js';
import type { SlotContribution } from '../slots/types.js';
import type { RailItem } from './types.js';

export interface AppLayoutProps {
  items: RailItem[];
  contributions?: SlotContribution[];
  activeItemId?: string;
  onSelectItem?: (item: RailItem) => void;
  brand?: React.ReactNode;
  railFooter?: React.ReactNode;
  mobileTopLeft?: React.ReactNode;
  mobileTopRight?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function AppLayout({
  items,
  contributions = [],
  activeItemId,
  onSelectItem,
  brand,
  railFooter,
  mobileTopLeft,
  mobileTopRight,
  children,
  className,
}: AppLayoutProps) {
  const activeItem = items.find((i) => i.id === activeItemId) || items[0];

  return (
    <div
      data-slot="app-layout"
      className={cn(
        'yc-AppLayout-root flex h-screen w-screen overflow-hidden bg-bg text-fg',
        className
      )}
    >
      {/* Desktop sidebar rail */}
      <div className="hidden md:flex h-full shrink-0">
        <AppRail
          items={items}
          contributions={contributions}
          activeItemId={activeItemId}
          onSelectItem={onSelectItem}
          brand={brand}
          footer={railFooter}
        />
      </div>

      {/* Main app canvas */}
      <div className="flex flex-1 flex-col h-full overflow-hidden">
        {/* Mobile top bar */}
        <MobileTopBar
          title={activeItem?.label}
          leftSlot={mobileTopLeft}
          rightSlot={mobileTopRight}
        />

        {/* Scrollable content container with mobile bottom pad */}
        <main
          data-slot="main-content"
          className="yc-AppLayout-content flex-1 overflow-y-auto pb-16 md:pb-0"
        >
          {children}
        </main>

        {/* Mobile bottom tab bar */}
        <MobileTabBar
          items={items.slice(0, 5)}
          activeItemId={activeItemId}
          onSelectItem={onSelectItem}
        />
      </div>
    </div>
  );
}
