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
import type { SettingsSection } from './types.js';

export interface SettingsLayoutProps {
  sections: SettingsSection[];
  activeSectionId?: string;
  onSelectSection?: (id: string) => void;
  contributions?: SlotContribution[];
  slotProps?: SlotProps;
  children?: React.ReactNode;
  className?: string;
}

export function SettingsLayout({
  sections,
  activeSectionId,
  onSelectSection,
  contributions = [],
  slotProps,
  children,
  className,
}: SettingsLayoutProps) {
  // Merge static sections with pack-contributed settings.section slots
  const mergedSections: SettingsSection[] = React.useMemo(() => {
    const list = [...sections];
    const slotSections = contributions
      .filter((c) => c.slot === 'settings.section')
      .map((c) => ({
        id: c.id,
        title: c.title,
        order: c.order ?? 50,
        slotContribution: c,
      }));
    list.push(...slotSections);
    return list.sort((a, b) => (a.order ?? 50) - (b.order ?? 50));
  }, [sections, contributions]);

  const [selectedId, setSelectedId] = React.useState(
    activeSectionId || (mergedSections[0]?.id ?? '')
  );

  const currentId = activeSectionId !== undefined ? activeSectionId : selectedId;
  const currentSection = mergedSections.find((s) => s.id === currentId) || mergedSections[0];

  const handleSelect = (id: string) => {
    setSelectedId(id);
    onSelectSection?.(id);
  };

  return (
    <div
      data-slot="settings-layout"
      className={cn(
        'yc-SettingsLayout-root flex flex-col md:flex-row gap-6 w-full max-w-6xl mx-auto p-4 md:p-6',
        className
      )}
    >
      {/* Sidebar nav */}
      <nav
        data-slot="nav"
        className="yc-SettingsLayout-nav w-full md:w-64 shrink-0 flex flex-col gap-1"
        aria-label="Settings navigation"
      >
        <h2 className="text-lg font-bold text-fg px-3 pb-3">Settings</h2>
        {mergedSections.map((sec) => {
          const isActive = sec.id === currentId;
          return (
            <button
              key={sec.id}
              type="button"
              onClick={() => handleSelect(sec.id)}
              data-slot="nav-item"
              data-active={isActive ? 'true' : undefined}
              className={cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors text-start',
                isActive
                  ? 'bg-surface-2 text-fg font-semibold shadow-1'
                  : 'text-fg-muted hover:bg-surface-2/60 hover:text-fg'
              )}
            >
              {sec.icon && <span className="inline-flex shrink-0">{sec.icon}</span>}
              <span className="truncate">{sec.title}</span>
            </button>
          );
        })}
      </nav>

      {/* Content panel */}
      <main
        data-slot="content"
        className="yc-SettingsLayout-content flex-1 rounded-xl border border-border bg-surface p-6 shadow-1"
      >
        {currentSection && (
          <div>
            <div className="border-b border-border pb-4 mb-6">
              <h3 className="text-xl font-bold text-fg">{currentSection.title}</h3>
              {currentSection.description && (
                <p className="mt-1 text-sm text-fg-muted">{currentSection.description}</p>
              )}
            </div>

            {currentSection.slotContribution && slotProps ? (
              <SlotRenderer
                contribution={currentSection.slotContribution}
                slotProps={slotProps}
              />
            ) : currentSection.component ? (
              <currentSection.component />
            ) : (
              children
            )}
          </div>
        )}
      </main>
    </div>
  );
}
