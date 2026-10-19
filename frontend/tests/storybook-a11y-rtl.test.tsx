/*
 * Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

import * as React from 'react';
import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import { UiProvider } from '../src/provider/UiProvider.js';
import {
  PrimitivesShowcase,
  ChatAndApprovalShowcase,
  CalendarAndRemindersShowcase,
  NotesProfilesTasksShowcase,
  ShellAndSettingsShowcase,
} from '../stories/DesignSystem.stories.js';

const STORIES = [
  { name: 'PrimitivesShowcase', Component: PrimitivesShowcase },
  { name: 'ChatAndApprovalShowcase', Component: ChatAndApprovalShowcase },
  { name: 'CalendarAndRemindersShowcase', Component: CalendarAndRemindersShowcase },
  { name: 'NotesProfilesTasksShowcase', Component: NotesProfilesTasksShowcase },
  { name: 'ShellAndSettingsShowcase', Component: ShellAndSettingsShowcase },
];

describe('U7 Storybook Visual, Theme (Light/Dark), RTL & A11y Regression Matrix', () => {
  for (const theme of ['light', 'dark'] as const) {
    for (const dir of ['ltr', 'rtl'] as const) {
      for (const { name, Component } of STORIES) {
        it(`renders ${name} cleanly in theme=${theme} dir=${dir} with stable yc-* classes, data-slot attributes, and accessible buttons`, () => {
          const html = renderToString(
            <div data-theme={theme} dir={dir}>
              <UiProvider product={{ name: 'TestApp' }} storageNamespace="test" defaultTheme={theme}>
                <Component />
              </UiProvider>
            </div>
          );

          const container = document.createElement('div');
          container.innerHTML = html;

          // 1. Must render at least one stable yc-* component class and data-slot attribute
          const slotted = container.querySelectorAll('[data-slot]');
          expect(slotted.length).toBeGreaterThan(0);

          const ycElements = Array.from(container.querySelectorAll('*')).filter((el: Element) =>
            Array.from(el.classList).some((c: string) => c.startsWith('yc-'))
          );
          expect(ycElements.length).toBeGreaterThan(0);

          // 2. Every button must have an accessible name (textContent or aria-label)
          const buttons = container.querySelectorAll('button');
          buttons.forEach((btn: HTMLButtonElement) => {
            const label = (btn.textContent || '').trim() || btn.getAttribute('aria-label') || '';
            expect(label.length).toBeGreaterThan(0);
          });
        });
      }
    }
  }
});
