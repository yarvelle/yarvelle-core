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

import { execFileSync } from 'node:child_process';
import * as fs from 'node:fs';
import { createRequire } from 'node:module';
import * as path from 'node:path';
import tailwindcss from 'tailwindcss';
import { beforeAll, describe, expect, it } from 'vitest';

import { yarvelleUiContentGlob as rootContentGlob } from '../src/index.js';
import { yarvellePreset, yarvelleUiContentGlob } from '../src/tokens/index.js';
import presetDefault, {
  yarvelleUiContentGlob as presetContentGlob,
} from '../src/tokens/tailwind-preset.js';

const pkgDir = path.resolve(__dirname, '..');
const srcDir = path.join(pkgDir, 'src');
const distEntry = path.join(pkgDir, 'dist', 'index.js');

const reqFromTw = createRequire(
  createRequire(import.meta.url).resolve('tailwindcss/package.json')
);
const postcss = reqFromTw('postcss') as (plugins: unknown[]) => {
  process: (css: string, opts: { from?: string }) => Promise<{ css: string }>;
};

function collectTsxFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (fs.statSync(full).isDirectory()) {
      collectTsxFiles(full, acc);
    } else if (entry.endsWith('.tsx')) {
      acc.push(full);
    }
  }
  return acc;
}

const NON_CLASS_LITERALS = new Set([
  'bottom-end',
  'bottom-start',
  'content',
  'end-slot',
  'inline-error',
  'start-slot',
  'top-end',
  'top-start',
]);

const UTILITY_TOKEN_RE =
  /^(?:hover:|focus:|focus-visible:|active:|disabled:|peer-checked:|after:|before:|sm:|md:|lg:|xl:|rtl:|ltr:|group-hover:|aria-selected:|data-\[[^\]]+\]:)*-?(?:bg|text|border|ring|shadow|rounded|p|px|py|pt|pb|ps|pe|m|mx|my|mt|mb|ms|me|w|h|min-w|min-h|max-w|max-h|gap|space-x|space-y|divide-x|divide-y|inset|top|bottom|start|end|z|opacity|font|leading|tracking|transition|duration|ease|animate|flex|inline-flex|grid|block|inline-block|inline|hidden|sr-only|items|justify|self|shrink|grow|truncate|line-clamp|overflow|whitespace|break|select|cursor|pointer-events|outline|underline)(?:$|[-/[]\S*)$/;

function extractComponentUtilityClasses(): string[] {
  const classes = new Set<string>();
  for (const file of collectTsxFiles(srcDir)) {
    const source = fs.readFileSync(file, 'utf-8');
    // Match double-quoted and backtick string literals without splitting escaped quotes inside class tokens
    const literalPatterns = [/"([^"\n]+)"/g, /'((?:\\'|[^'\n])+)'/g, /`([^`\n$]+)`/g];
    for (const pattern of literalPatterns) {
      for (const match of source.matchAll(pattern)) {
        const raw = match[1].replace(/\\'/g, "'");
        for (const token of raw.split(/\s+/)) {
          if (
            token &&
            !NON_CLASS_LITERALS.has(token) &&
            !token.startsWith('yc-') &&
            UTILITY_TOKEN_RE.test(token)
          ) {
            classes.add(token);
          }
        }
      }
    }
  }
  return [...classes].sort();
}

function toEscapedCssSelector(utilityClass: string): string {
  return '.' + utilityClass.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
}

describe('yarvellePreset & yarvelleUiContentGlob Tailwind CSS Contract (#54)', () => {
  beforeAll(() => {
    // Always rebuild dist/ so the CSS contract validates the exact compiled output
    execFileSync('pnpm', ['run', 'build'], { cwd: pkgDir, stdio: 'pipe' });
  }, 60_000);

  it('places semantic tokens under theme.extend without wiping Tailwind base theme', () => {
    expect(yarvellePreset).toBe(presetDefault);
    expect(yarvellePreset.theme?.colors).toBeUndefined();
    expect(yarvellePreset.theme?.spacing).toBeUndefined();
    expect(yarvellePreset.theme?.extend?.colors).toBeDefined();
    expect(yarvellePreset.theme?.extend?.spacing).toBeDefined();
  });

  it('exports yarvelleUiContentGlob from tokens, tailwind-preset, and root entry points', () => {
    expect(yarvelleUiContentGlob).toBeTypeOf('function');
    expect(presetContentGlob).toBe(yarvelleUiContentGlob);
    expect(rootContentGlob).toBe(yarvelleUiContentGlob);

    const resolvedGlob = yarvelleUiContentGlob();
    const expectedRoot = pkgDir.replace(/\\/g, '/');
    expect(resolvedGlob).toBe(`${expectedRoot}/dist/**/*.{js,mjs}`);
    expect(fs.existsSync(distEntry)).toBe(true);

    expect(yarvelleUiContentGlob('/workspace/apps/web/')).toBe(
      '/workspace/apps/web/node_modules/@yarvelle/ui/dist/**/*.{js,mjs}'
    );
    expect(yarvelleUiContentGlob('C:\\workspace\\apps\\web\\')).toBe(
      'C:/workspace/apps/web/node_modules/@yarvelle/ui/dist/**/*.{js,mjs}'
    );
    expect(yarvelleUiContentGlob('/workspace/node_modules/@yarvelle/ui')).toBe(
      '/workspace/node_modules/@yarvelle/ui/dist/**/*.{js,mjs}'
    );
  });

  it('preserves standard Tailwind base palette utilities alongside semantic Yarvelle tokens', async () => {
    const result = await postcss([
      tailwindcss({
        presets: [yarvellePreset],
        content: [
          {
            raw: '<div class="text-white bg-black bg-slate-500 text-red-600 border-amber-300 bg-primary text-fg-on-primary"></div>',
          },
        ],
      }),
    ]).process('@tailwind utilities;', { from: undefined });

    expect(result.css).toContain('.text-white');
    expect(result.css).toContain('.bg-black');
    expect(result.css).toContain('.bg-slate-500');
    expect(result.css).toContain('.text-red-600');
    expect(result.css).toContain('.border-amber-300');
    expect(result.css).toContain('.bg-primary');
    expect(result.css).toContain('var(--ui-primary)');
    expect(result.css).toContain('.text-fg-on-primary');
    expect(result.css).toContain('var(--ui-fg-on-primary)');
  });

  it('emits non-empty CSS rules for every utility class referenced across @yarvelle/ui dist/', async () => {
    const componentClasses = extractComponentUtilityClasses();
    expect(componentClasses.length).toBeGreaterThan(200);

    const result = await postcss([
      tailwindcss({
        presets: [yarvellePreset],
        content: [yarvelleUiContentGlob()],
      }),
    ]).process('@tailwind utilities;', { from: undefined });

    const missingClasses = componentClasses.filter(
      (cls) => !result.css.includes(toEscapedCssSelector(cls))
    );
    expect(missingClasses).toEqual([]);

    // Contrast-critical foreground/background and alpha-modifier rules must resolve cleanly
    expect(result.css).toContain('.hover\\:text-fg-on-primary:hover');
    expect(result.css).toContain('.hover\\:bg-fg\\/10:hover');
    expect(result.css).toContain('color-mix(in srgb, var(--ui-fg) 10%, transparent)');
    expect(result.css).toContain('.bg-surface-2\\/60');
    expect(result.css).toContain('.after\\:bg-surface::after');
    expect(result.css).toContain('.peer:checked ~ .peer-checked\\:after\\:bg-fg-on-primary::after');
  });
});
