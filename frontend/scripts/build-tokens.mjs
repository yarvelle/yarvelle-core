#!/usr/bin/env node
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

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const primitives = JSON.parse(fs.readFileSync(path.join(rootDir, 'tokens', 'primitives.json'), 'utf-8'));
const semanticLight = JSON.parse(fs.readFileSync(path.join(rootDir, 'tokens', 'semantic.light.json'), 'utf-8'));
const semanticDark = JSON.parse(fs.readFileSync(path.join(rootDir, 'tokens', 'semantic.dark.json'), 'utf-8'));

function flattenTokens(obj, prefix = '') {
  let res = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}-${k}` : k;
    if (v && typeof v === 'object' && '$value' in v) {
      res[key] = v.$value;
    } else if (v && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(res, flattenTokens(v, key));
    }
  }
  return res;
}

// 1. Build tokens.css
const cssLines = [];
cssLines.push('/*');
cssLines.push(' * Yarvelle Core UI Design Tokens');
cssLines.push(' * Emitted automatically by scripts/build-tokens.mjs — DO NOT EDIT DIRECTLY');
cssLines.push(' */');
cssLines.push('');
cssLines.push(':root {');
cssLines.push('  color-scheme: light;');
cssLines.push('');
cssLines.push('  /* Surfaces */');
cssLines.push(`  --ui-canvas: ${semanticLight.color.bg.canvas.$value};`);
cssLines.push(`  --ui-surface: ${semanticLight.color.bg.surface.$value};`);
cssLines.push(`  --ui-surface-2: ${semanticLight.color.bg.surface2.$value};`);
cssLines.push(`  --ui-surface-3: ${semanticLight.color.bg.surface3.$value};`);
cssLines.push(`  --ui-rail: ${semanticLight.color.bg.rail.$value};`);
cssLines.push(`  --ui-overlay: ${semanticLight.color.bg.overlay.$value};`);
cssLines.push('');
cssLines.push('  /* Text */');
cssLines.push(`  --ui-fg: ${semanticLight.color.fg.default.$value};`);
cssLines.push(`  --ui-fg-muted: ${semanticLight.color.fg.muted.$value};`);
cssLines.push(`  --ui-fg-subtle: ${semanticLight.color.fg.subtle.$value};`);
cssLines.push(`  --ui-fg-on-primary: ${semanticLight.color.fg.onPrimary.$value};`);
cssLines.push(`  --ui-fg-link: ${semanticLight.color.fg.link.$value};`);
cssLines.push('');
cssLines.push('  /* Lines / Borders */');
cssLines.push(`  --ui-border: ${semanticLight.color.border.default.$value};`);
cssLines.push(`  --ui-border-strong: ${semanticLight.color.border.strong.$value};`);
cssLines.push('');
cssLines.push('  /* Primary Action */');
cssLines.push(`  --ui-primary: ${semanticLight.color.action.primary.bg.$value};`);
cssLines.push(`  --ui-primary-hover: ${semanticLight.color.action.primary.bgHover.$value};`);
cssLines.push(`  --ui-primary-fg: ${semanticLight.color.action.primary.fg.$value};`);
cssLines.push(`  --ui-primary-soft: ${semanticLight.color.action.primary.softBg.$value};`);
cssLines.push(`  --ui-primary-soft-fg: ${semanticLight.color.action.primary.softFg.$value};`);
cssLines.push('');
cssLines.push('  /* Status */');
cssLines.push(`  --ui-info-bg: ${semanticLight.color.status.info.bg.$value};`);
cssLines.push(`  --ui-info-fg: ${semanticLight.color.status.info.fg.$value};`);
cssLines.push(`  --ui-info-border: ${semanticLight.color.status.info.border.$value};`);
cssLines.push(`  --ui-warn-bg: ${semanticLight.color.status.warn.bg.$value};`);
cssLines.push(`  --ui-warn-fg: ${semanticLight.color.status.warn.fg.$value};`);
cssLines.push(`  --ui-warn-border: ${semanticLight.color.status.warn.border.$value};`);
cssLines.push(`  --ui-danger-bg: ${semanticLight.color.status.danger.bg.$value};`);
cssLines.push(`  --ui-danger-fg: ${semanticLight.color.status.danger.fg.$value};`);
cssLines.push(`  --ui-danger-border: ${semanticLight.color.status.danger.border.$value};`);
cssLines.push(`  --ui-success-bg: ${semanticLight.color.status.success.bg.$value};`);
cssLines.push(`  --ui-success-fg: ${semanticLight.color.status.success.fg.$value};`);
cssLines.push(`  --ui-success-border: ${semanticLight.color.status.success.border.$value};`);
cssLines.push('');
cssLines.push('  /* Emergency */');
cssLines.push(`  --ui-emergency: ${semanticLight.color.emergency.bg.$value};`);
cssLines.push(`  --ui-emergency-fg: ${semanticLight.color.emergency.fg.$value};`);
cssLines.push('');
cssLines.push('  /* Focus */');
cssLines.push(`  --ui-focus: ${semanticLight.color.focus.ring.$value};`);
cssLines.push(`  --ui-focus-offset: ${semanticLight.color.focus.offset.$value};`);
cssLines.push('');
cssLines.push('  /* Member Identity */');
for (let i = 1; i <= 5; i++) {
  cssLines.push(`  --ui-member-${i}-bg: ${semanticLight.color.member[i].bg.$value};`);
  cssLines.push(`  --ui-member-${i}-fg: ${semanticLight.color.member[i].fg.$value};`);
}
cssLines.push('');
cssLines.push('  /* Scope Domains */');
for (const dom of ['health', 'finance', 'education', 'household']) {
  cssLines.push(`  --ui-scope-${dom}-bg: ${semanticLight.color.scope[dom].bg.$value};`);
  cssLines.push(`  --ui-scope-${dom}-fg: ${semanticLight.color.scope[dom].fg.$value};`);
}
cssLines.push('');
cssLines.push('  /* Risk Tiers */');
for (const tier of ['low', 'medium', 'high', 'critical']) {
  cssLines.push(`  --ui-risk-${tier}-bg: ${semanticLight.color.risk[tier].bg.$value};`);
  cssLines.push(`  --ui-risk-${tier}-fg: ${semanticLight.color.risk[tier].fg.$value};`);
  cssLines.push(`  --ui-risk-${tier}-border: ${semanticLight.color.risk[tier].border.$value};`);
}
cssLines.push('');
cssLines.push('  /* Typography */');
cssLines.push(`  --ui-font-sans: ${primitives.font.family.sans.$value};`);
cssLines.push(`  --ui-font-display: ${primitives.font.family.display.$value};`);
cssLines.push(`  --ui-font-mono: ${primitives.font.family.mono.$value};`);
for (const sz of ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', '4xl']) {
  cssLines.push(`  --ui-text-${sz}: ${primitives.font.size[sz].$value};`);
  cssLines.push(`  --ui-leading-${sz}: ${primitives.font.lineHeight[sz].$value};`);
}
for (const [w, val] of Object.entries(primitives.font.weight)) {
  cssLines.push(`  --ui-weight-${w}: ${val.$value};`);
}
cssLines.push('');
cssLines.push('  /* Spacing */');
for (const [s, val] of Object.entries(primitives.space)) {
  cssLines.push(`  --ui-space-${s}: ${val.$value};`);
}
cssLines.push('');
cssLines.push('  /* Radius */');
for (const [r, val] of Object.entries(primitives.radius)) {
  cssLines.push(`  --ui-radius-${r}: ${val.$value};`);
}
cssLines.push('');
cssLines.push('  /* Shadow */');
for (const [sh, val] of Object.entries(primitives.shadow)) {
  cssLines.push(`  --ui-shadow-${sh}: ${val.$value};`);
}
cssLines.push('');
cssLines.push('  /* Sizing and Layout */');
cssLines.push(`  --ui-tap: ${primitives.size.tap.$value};`);
cssLines.push(`  --ui-rail-w: ${primitives.layout.railWidth.$value};`);
cssLines.push(`  --ui-content-max: ${primitives.layout.contentMax.$value};`);
cssLines.push(`  --ui-content-wide: ${primitives.layout.contentWide.$value};`);
cssLines.push(`  --ui-topbar-h: ${primitives.layout.topbarHeight.$value};`);
cssLines.push(`  --ui-tabbar-h: ${primitives.layout.tabbarHeight.$value};`);
cssLines.push('');
cssLines.push('  /* Motion */');
cssLines.push(`  --ui-ease: ${primitives.motion.easing.default.$value};`);
cssLines.push(`  --ui-duration-fast: ${primitives.motion.duration.fast.$value};`);
cssLines.push(`  --ui-duration-base: ${primitives.motion.duration.base.$value};`);
cssLines.push(`  --ui-duration-slow: ${primitives.motion.duration.slow.$value};`);
cssLines.push('');
cssLines.push('  /* Z-Index */');
for (const [z, val] of Object.entries(primitives.z)) {
  cssLines.push(`  --ui-z-${z}: ${val.$value};`);
}
cssLines.push('}');
cssLines.push('');
cssLines.push('[data-theme="dark"], .dark {');
cssLines.push('  color-scheme: dark;');
cssLines.push('');
cssLines.push('  /* Surfaces */');
cssLines.push(`  --ui-canvas: ${semanticDark.color.bg.canvas.$value};`);
cssLines.push(`  --ui-surface: ${semanticDark.color.bg.surface.$value};`);
cssLines.push(`  --ui-surface-2: ${semanticDark.color.bg.surface2.$value};`);
cssLines.push(`  --ui-surface-3: ${semanticDark.color.bg.surface3.$value};`);
cssLines.push(`  --ui-rail: ${semanticDark.color.bg.rail.$value};`);
cssLines.push(`  --ui-overlay: ${semanticDark.color.bg.overlay.$value};`);
cssLines.push('');
cssLines.push('  /* Text */');
cssLines.push(`  --ui-fg: ${semanticDark.color.fg.default.$value};`);
cssLines.push(`  --ui-fg-muted: ${semanticDark.color.fg.muted.$value};`);
cssLines.push(`  --ui-fg-subtle: ${semanticDark.color.fg.subtle.$value};`);
cssLines.push(`  --ui-fg-on-primary: ${semanticDark.color.fg.onPrimary.$value};`);
cssLines.push(`  --ui-fg-link: ${semanticDark.color.fg.link.$value};`);
cssLines.push('');
cssLines.push('  /* Lines / Borders */');
cssLines.push(`  --ui-border: ${semanticDark.color.border.default.$value};`);
cssLines.push(`  --ui-border-strong: ${semanticDark.color.border.strong.$value};`);
cssLines.push('');
cssLines.push('  /* Primary Action */');
cssLines.push(`  --ui-primary: ${semanticDark.color.action.primary.bg.$value};`);
cssLines.push(`  --ui-primary-hover: ${semanticDark.color.action.primary.bgHover.$value};`);
cssLines.push(`  --ui-primary-fg: ${semanticDark.color.action.primary.fg.$value};`);
cssLines.push(`  --ui-primary-soft: ${semanticDark.color.action.primary.softBg.$value};`);
cssLines.push(`  --ui-primary-soft-fg: ${semanticDark.color.action.primary.softFg.$value};`);
cssLines.push('');
cssLines.push('  /* Status */');
cssLines.push(`  --ui-info-bg: ${semanticDark.color.status.info.bg.$value};`);
cssLines.push(`  --ui-info-fg: ${semanticDark.color.status.info.fg.$value};`);
cssLines.push(`  --ui-info-border: ${semanticDark.color.status.info.border.$value};`);
cssLines.push(`  --ui-warn-bg: ${semanticDark.color.status.warn.bg.$value};`);
cssLines.push(`  --ui-warn-fg: ${semanticDark.color.status.warn.fg.$value};`);
cssLines.push(`  --ui-warn-border: ${semanticDark.color.status.warn.border.$value};`);
cssLines.push(`  --ui-danger-bg: ${semanticDark.color.status.danger.bg.$value};`);
cssLines.push(`  --ui-danger-fg: ${semanticDark.color.status.danger.fg.$value};`);
cssLines.push(`  --ui-danger-border: ${semanticDark.color.status.danger.border.$value};`);
cssLines.push(`  --ui-success-bg: ${semanticDark.color.status.success.bg.$value};`);
cssLines.push(`  --ui-success-fg: ${semanticDark.color.status.success.fg.$value};`);
cssLines.push(`  --ui-success-border: ${semanticDark.color.status.success.border.$value};`);
cssLines.push('');
cssLines.push('  /* Emergency */');
cssLines.push(`  --ui-emergency: ${semanticDark.color.emergency.bg.$value};`);
cssLines.push(`  --ui-emergency-fg: ${semanticDark.color.emergency.fg.$value};`);
cssLines.push('');
cssLines.push('  /* Focus */');
cssLines.push(`  --ui-focus: ${semanticDark.color.focus.ring.$value};`);
cssLines.push(`  --ui-focus-offset: ${semanticDark.color.focus.offset.$value};`);
cssLines.push('');
cssLines.push('  /* Member Identity */');
for (let i = 1; i <= 5; i++) {
  cssLines.push(`  --ui-member-${i}-bg: ${semanticDark.color.member[i].bg.$value};`);
  cssLines.push(`  --ui-member-${i}-fg: ${semanticDark.color.member[i].fg.$value};`);
}
cssLines.push('');
cssLines.push('  /* Scope Domains */');
for (const dom of ['health', 'finance', 'education', 'household']) {
  cssLines.push(`  --ui-scope-${dom}-bg: ${semanticDark.color.scope[dom].bg.$value};`);
  cssLines.push(`  --ui-scope-${dom}-fg: ${semanticDark.color.scope[dom].fg.$value};`);
}
cssLines.push('');
cssLines.push('  /* Risk Tiers */');
for (const tier of ['low', 'medium', 'high', 'critical']) {
  cssLines.push(`  --ui-risk-${tier}-bg: ${semanticDark.color.risk[tier].bg.$value};`);
  cssLines.push(`  --ui-risk-${tier}-fg: ${semanticDark.color.risk[tier].fg.$value};`);
  cssLines.push(`  --ui-risk-${tier}-border: ${semanticDark.color.risk[tier].border.$value};`);
}
cssLines.push('');
cssLines.push('  /* Dark Shadows */');
for (const [sh, val] of Object.entries(semanticDark.shadow)) {
  cssLines.push(`  --ui-shadow-${sh}: ${val.$value};`);
}
cssLines.push('}');
cssLines.push('');

const tokensCssPath = path.join(rootDir, 'src', 'tokens', 'tokens.css');
fs.writeFileSync(tokensCssPath, cssLines.join('\n'));
console.log(`Generated tokens.css at ${tokensCssPath}`);

// 2. Build names.d.ts
const namesLines = [
  '// Emitted automatically by scripts/build-tokens.mjs — DO NOT EDIT DIRECTLY',
  '',
  'export type UiColorToken =',
  '  | "canvas" | "surface" | "surface-2" | "surface-3" | "rail" | "overlay"',
  '  | "fg" | "fg-muted" | "fg-subtle" | "fg-on-primary" | "fg-link"',
  '  | "border" | "border-strong"',
  '  | "primary" | "primary-hover" | "primary-fg" | "primary-soft" | "primary-soft-fg"',
  '  | "info-bg" | "info-fg" | "info-border"',
  '  | "warn-bg" | "warn-fg" | "warn-border"',
  '  | "danger-bg" | "danger-fg" | "danger-border"',
  '  | "success-bg" | "success-fg" | "success-border"',
  '  | "emergency" | "emergency-fg" | "focus" | "focus-offset"',
  '  | "member-1-bg" | "member-1-fg" | "member-2-bg" | "member-2-fg" | "member-3-bg" | "member-3-fg" | "member-4-bg" | "member-4-fg" | "member-5-bg" | "member-5-fg"',
  '  | "scope-health-bg" | "scope-health-fg" | "scope-finance-bg" | "scope-finance-fg" | "scope-education-bg" | "scope-education-fg" | "scope-household-bg" | "scope-household-fg"',
  '  | "risk-low-bg" | "risk-low-fg" | "risk-low-border" | "risk-medium-bg" | "risk-medium-fg" | "risk-medium-border" | "risk-high-bg" | "risk-high-fg" | "risk-high-border" | "risk-critical-bg" | "risk-critical-fg" | "risk-critical-border";',
  '',
  'export type UiSpaceToken = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "8" | "10" | "12" | "16";',
  'export type UiRadiusToken = "sm" | "md" | "lg" | "xl" | "full";',
  'export type UiShadowToken = "0" | "1" | "2" | "3";',
  'export type UiTextSizeToken = "xs" | "sm" | "md" | "lg" | "xl" | "2xl" | "3xl" | "4xl";',
  'export type UiZIndexToken = "rail" | "sticky" | "popover" | "modal" | "toast" | "skip";',
  '',
];
const namesDtsPath = path.join(rootDir, 'src', 'tokens', 'names.d.ts');
fs.writeFileSync(namesDtsPath, namesLines.join('\n'));
console.log(`Generated names.d.ts at ${namesDtsPath}`);

// 3. Build tailwind-preset.ts
const tailwindPresetContent = `// Emitted automatically by scripts/build-tokens.mjs — DO NOT EDIT DIRECTLY
import type { Config } from 'tailwindcss';

export const yarvellePreset: Config = {
  content: [],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      canvas: 'var(--ui-canvas)',
      surface: {
        DEFAULT: 'var(--ui-surface)',
        2: 'var(--ui-surface-2)',
        3: 'var(--ui-surface-3)',
      },
      rail: 'var(--ui-rail)',
      overlay: 'var(--ui-overlay)',
      fg: {
        DEFAULT: 'var(--ui-fg)',
        muted: 'var(--ui-fg-muted)',
        subtle: 'var(--ui-fg-subtle)',
        'on-primary': 'var(--ui-fg-on-primary)',
        link: 'var(--ui-fg-link)',
      },
      border: {
        DEFAULT: 'var(--ui-border)',
        strong: 'var(--ui-border-strong)',
      },
      primary: {
        DEFAULT: 'var(--ui-primary)',
        hover: 'var(--ui-primary-hover)',
        fg: 'var(--ui-primary-fg)',
        soft: 'var(--ui-primary-soft)',
        'soft-fg': 'var(--ui-primary-soft-fg)',
      },
      info: {
        bg: 'var(--ui-info-bg)',
        fg: 'var(--ui-info-fg)',
        border: 'var(--ui-info-border)',
      },
      warn: {
        bg: 'var(--ui-warn-bg)',
        fg: 'var(--ui-warn-fg)',
        border: 'var(--ui-warn-border)',
      },
      danger: {
        bg: 'var(--ui-danger-bg)',
        fg: 'var(--ui-danger-fg)',
        border: 'var(--ui-danger-border)',
      },
      success: {
        bg: 'var(--ui-success-bg)',
        fg: 'var(--ui-success-fg)',
        border: 'var(--ui-success-border)',
      },
      emergency: {
        DEFAULT: 'var(--ui-emergency)',
        fg: 'var(--ui-emergency-fg)',
      },
      focus: {
        DEFAULT: 'var(--ui-focus)',
        offset: 'var(--ui-focus-offset)',
      },
      member: {
        1: { bg: 'var(--ui-member-1-bg)', fg: 'var(--ui-member-1-fg)' },
        2: { bg: 'var(--ui-member-2-bg)', fg: 'var(--ui-member-2-fg)' },
        3: { bg: 'var(--ui-member-3-bg)', fg: 'var(--ui-member-3-fg)' },
        4: { bg: 'var(--ui-member-4-bg)', fg: 'var(--ui-member-4-fg)' },
        5: { bg: 'var(--ui-member-5-bg)', fg: 'var(--ui-member-5-fg)' },
      },
      scope: {
        health: { bg: 'var(--ui-scope-health-bg)', fg: 'var(--ui-scope-health-fg)' },
        finance: { bg: 'var(--ui-scope-finance-bg)', fg: 'var(--ui-scope-finance-fg)' },
        education: { bg: 'var(--ui-scope-education-bg)', fg: 'var(--ui-scope-education-fg)' },
        household: { bg: 'var(--ui-scope-household-bg)', fg: 'var(--ui-scope-household-fg)' },
      },
      risk: {
        low: { bg: 'var(--ui-risk-low-bg)', fg: 'var(--ui-risk-low-fg)', border: 'var(--ui-risk-low-border)' },
        medium: { bg: 'var(--ui-risk-medium-bg)', fg: 'var(--ui-risk-medium-fg)', border: 'var(--ui-risk-medium-border)' },
        high: { bg: 'var(--ui-risk-high-bg)', fg: 'var(--ui-risk-high-fg)', border: 'var(--ui-risk-high-border)' },
        critical: { bg: 'var(--ui-risk-critical-bg)', fg: 'var(--ui-risk-critical-fg)', border: 'var(--ui-risk-critical-border)' },
      },
    },
    spacing: {
      0: 'var(--ui-space-0)',
      1: 'var(--ui-space-1)',
      2: 'var(--ui-space-2)',
      3: 'var(--ui-space-3)',
      4: 'var(--ui-space-4)',
      5: 'var(--ui-space-5)',
      6: 'var(--ui-space-6)',
      8: 'var(--ui-space-8)',
      10: 'var(--ui-space-10)',
      12: 'var(--ui-space-12)',
      16: 'var(--ui-space-16)',
    },
    fontFamily: {
      sans: ['var(--ui-font-sans)'],
      display: ['var(--ui-font-display)'],
      mono: ['var(--ui-font-mono)'],
    },
    fontSize: {
      xs: ['var(--ui-text-xs)', { lineHeight: 'var(--ui-leading-xs)' }],
      sm: ['var(--ui-text-sm)', { lineHeight: 'var(--ui-leading-sm)' }],
      base: ['var(--ui-text-md)', { lineHeight: 'var(--ui-leading-md)' }],
      md: ['var(--ui-text-md)', { lineHeight: 'var(--ui-leading-md)' }],
      lg: ['var(--ui-text-lg)', { lineHeight: 'var(--ui-leading-lg)' }],
      xl: ['var(--ui-text-xl)', { lineHeight: 'var(--ui-leading-xl)' }],
      '2xl': ['var(--ui-text-2xl)', { lineHeight: 'var(--ui-leading-2xl)' }],
      '3xl': ['var(--ui-text-3xl)', { lineHeight: 'var(--ui-leading-3xl)' }],
      '4xl': ['var(--ui-text-4xl)', { lineHeight: 'var(--ui-leading-4xl)' }],
    },
    borderRadius: {
      none: '0px',
      sm: 'var(--ui-radius-sm)',
      md: 'var(--ui-radius-md)',
      lg: 'var(--ui-radius-lg)',
      xl: 'var(--ui-radius-xl)',
      full: 'var(--ui-radius-full)',
    },
    boxShadow: {
      0: 'var(--ui-shadow-0)',
      1: 'var(--ui-shadow-1)',
      2: 'var(--ui-shadow-2)',
      3: 'var(--ui-shadow-3)',
    },
    minHeight: {
      tap: 'var(--ui-tap)',
    },
    minWidth: {
      tap: 'var(--ui-tap)',
    },
    transitionTimingFunction: {
      ui: 'var(--ui-ease)',
    },
    transitionDuration: {
      fast: 'var(--ui-duration-fast)',
      base: 'var(--ui-duration-base)',
      slow: 'var(--ui-duration-slow)',
    },
    zIndex: {
      rail: 'var(--ui-z-rail)',
      sticky: 'var(--ui-z-sticky)',
      popover: 'var(--ui-z-popover)',
      modal: 'var(--ui-z-modal)',
      toast: 'var(--ui-z-toast)',
      skip: 'var(--ui-z-skip)',
    },
  },
};

export default yarvellePreset;
`;

const tailwindPresetPath = path.join(rootDir, 'src', 'tokens', 'tailwind-preset.ts');
fs.writeFileSync(tailwindPresetPath, tailwindPresetContent);
console.log(`Generated tailwind-preset.ts at ${tailwindPresetPath}`);
