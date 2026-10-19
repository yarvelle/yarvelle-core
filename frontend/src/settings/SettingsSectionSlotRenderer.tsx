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
import { SlotRenderer } from '../slots/SlotRenderer.js';
import type { SlotContribution, SlotProps } from '../slots/types.js';

export interface SettingsSectionSlotRendererProps {
  contributions: SlotContribution[];
  slotProps: SlotProps;
  className?: string;
}

export function SettingsSectionSlotRenderer({
  contributions,
  slotProps,
  className,
}: SettingsSectionSlotRendererProps) {
  const sectionSlots = contributions.filter((c) => c.slot === 'settings.section');

  return (
    <div
      data-slot="settings-section-slot-renderer"
      className={cn('yc-SettingsSectionSlotRenderer-root space-y-6', className)}
    >
      {sectionSlots.map((c) => (
        <div
          key={c.id}
          className="rounded-xl border border-border bg-surface p-6 shadow-1"
          data-slot="slot-section"
        >
          <div className="border-b border-border pb-3 mb-4">
            <h3 className="text-base font-semibold text-fg">{c.title}</h3>
          </div>
          <SlotRenderer contribution={c} slotProps={slotProps} />
        </div>
      ))}
    </div>
  );
}
