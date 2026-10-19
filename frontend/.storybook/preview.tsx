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
import { UiProvider } from '../src/provider/UiProvider.js';

export const globalTypes = {
  theme: {
    name: 'Theme',
    description: 'Semantic token theme',
    defaultValue: 'light',
    toolbar: {
      icon: 'mirror',
      items: ['light', 'dark'],
    },
  },
  direction: {
    name: 'Direction',
    description: 'Text direction (LTR / RTL)',
    defaultValue: 'ltr',
    toolbar: {
      icon: 'globe',
      items: ['ltr', 'rtl'],
    },
  },
};

export const decorators = [
  (Story: React.ComponentType, context: { globals?: { theme?: 'light' | 'dark'; direction?: 'ltr' | 'rtl' } }) => {
    const theme = context.globals?.theme ?? 'light';
    const dir = context.globals?.direction ?? 'ltr';
    return (
      <div data-theme={theme} dir={dir} className="min-h-screen bg-ui-bg text-ui-fg p-4">
        <UiProvider product={{ name: 'Yarvelle Core' }} storageNamespace="yarvelle_sb" defaultTheme={theme}>
          <Story />
        </UiProvider>
      </div>
    );
  },
];
