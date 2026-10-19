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
