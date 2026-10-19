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
