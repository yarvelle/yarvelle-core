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

// Emitted automatically by scripts/build-tokens.mjs — DO NOT EDIT DIRECTLY
import type { Config } from 'tailwindcss';
import { yarvelleUiContentGlob } from './content-glob.js';

type AlphaColorParams = {
  opacityVariable?: string;
  opacityValue?: string;
};

function withAlpha(cssVar: string): string {
  return (({ opacityValue }: AlphaColorParams): string => {
    if (
      opacityValue === undefined ||
      opacityValue === '1' ||
      opacityValue.startsWith('var(--tw-')
    ) {
      return `var(${cssVar})`;
    }
    const numeric = Number(opacityValue);
    const pct = Number.isFinite(numeric)
      ? `${Math.round(numeric * 10000) / 100}%`
      : `calc(${opacityValue} * 100%)`;
    return `color-mix(in srgb, var(${cssVar}) ${pct}, transparent)`;
  }) as unknown as string;
}

export const yarvellePreset: Config = {
  content: [],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: withAlpha('--ui-canvas'),
        surface: {
          DEFAULT: withAlpha('--ui-surface'),
          2: withAlpha('--ui-surface-2'),
          3: withAlpha('--ui-surface-3'),
        },
        rail: withAlpha('--ui-rail'),
        overlay: withAlpha('--ui-overlay'),
        fg: {
          DEFAULT: withAlpha('--ui-fg'),
          muted: withAlpha('--ui-fg-muted'),
          subtle: withAlpha('--ui-fg-subtle'),
          'on-primary': withAlpha('--ui-fg-on-primary'),
          link: withAlpha('--ui-fg-link'),
        },
        border: {
          DEFAULT: withAlpha('--ui-border'),
          strong: withAlpha('--ui-border-strong'),
        },
        primary: {
          DEFAULT: withAlpha('--ui-primary'),
          hover: withAlpha('--ui-primary-hover'),
          fg: withAlpha('--ui-primary-fg'),
          soft: withAlpha('--ui-primary-soft'),
          'soft-fg': withAlpha('--ui-primary-soft-fg'),
        },
        info: {
          bg: withAlpha('--ui-info-bg'),
          fg: withAlpha('--ui-info-fg'),
          border: withAlpha('--ui-info-border'),
        },
        warn: {
          bg: withAlpha('--ui-warn-bg'),
          fg: withAlpha('--ui-warn-fg'),
          border: withAlpha('--ui-warn-border'),
        },
        danger: {
          bg: withAlpha('--ui-danger-bg'),
          fg: withAlpha('--ui-danger-fg'),
          border: withAlpha('--ui-danger-border'),
        },
        success: {
          bg: withAlpha('--ui-success-bg'),
          fg: withAlpha('--ui-success-fg'),
          border: withAlpha('--ui-success-border'),
        },
        emergency: {
          DEFAULT: withAlpha('--ui-emergency'),
          fg: withAlpha('--ui-emergency-fg'),
        },
        focus: {
          DEFAULT: withAlpha('--ui-focus'),
          offset: withAlpha('--ui-focus-offset'),
        },
        member: {
          1: { bg: withAlpha('--ui-member-1-bg'), fg: withAlpha('--ui-member-1-fg') },
          2: { bg: withAlpha('--ui-member-2-bg'), fg: withAlpha('--ui-member-2-fg') },
          3: { bg: withAlpha('--ui-member-3-bg'), fg: withAlpha('--ui-member-3-fg') },
          4: { bg: withAlpha('--ui-member-4-bg'), fg: withAlpha('--ui-member-4-fg') },
          5: { bg: withAlpha('--ui-member-5-bg'), fg: withAlpha('--ui-member-5-fg') },
        },
        scope: {
          health: { bg: withAlpha('--ui-scope-health-bg'), fg: withAlpha('--ui-scope-health-fg') },
          finance: { bg: withAlpha('--ui-scope-finance-bg'), fg: withAlpha('--ui-scope-finance-fg') },
          education: { bg: withAlpha('--ui-scope-education-bg'), fg: withAlpha('--ui-scope-education-fg') },
          household: { bg: withAlpha('--ui-scope-household-bg'), fg: withAlpha('--ui-scope-household-fg') },
        },
        risk: {
          low: { bg: withAlpha('--ui-risk-low-bg'), fg: withAlpha('--ui-risk-low-fg'), border: withAlpha('--ui-risk-low-border') },
          medium: { bg: withAlpha('--ui-risk-medium-bg'), fg: withAlpha('--ui-risk-medium-fg'), border: withAlpha('--ui-risk-medium-border') },
          high: { bg: withAlpha('--ui-risk-high-bg'), fg: withAlpha('--ui-risk-high-fg'), border: withAlpha('--ui-risk-high-border') },
          critical: { bg: withAlpha('--ui-risk-critical-bg'), fg: withAlpha('--ui-risk-critical-fg'), border: withAlpha('--ui-risk-critical-border') },
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
  },
};

export { yarvelleUiContentGlob };
export default yarvellePreset;
