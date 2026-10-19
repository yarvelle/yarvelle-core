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

import { defineConfig } from 'tsup';

export default defineConfig({
  entry: {
    index: 'src/index.ts',
    'tokens/index': 'src/tokens/index.ts',
    'tokens/tailwind-preset': 'src/tokens/tailwind-preset.ts',
    'slots/index': 'src/slots/index.ts',
    'testing/index': 'src/testing/index.ts',
    'lib/index': 'src/lib/index.ts',
    'lib/storage-namespace': 'src/lib/storage-namespace.ts',
    'lib/cn': 'src/lib/cn.ts',
    'lib/api/index': 'src/lib/api/index.ts',
    'lib/sse/index': 'src/lib/sse/index.ts',
    'lib/auth/index': 'src/lib/auth/index.ts',
    'lib/i18n/index': 'src/lib/i18n/index.ts',
  },
  format: ['esm'],
  dts: true,
  clean: false,
  splitting: false,
  sourcemap: true,
  external: ['react', 'react-dom'],
});
