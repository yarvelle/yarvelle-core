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

import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

function parseHex(hex: string): [number, number, number] {
  let clean = hex.replace('#', '').trim();
  if (clean.length === 3) {
    clean = clean.split('').map((c) => c + c).join('');
  }
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return [r, g, b];
}

function sRgbToLinear(c: number): number {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  const rLin = sRgbToLinear(r);
  const gLin = sRgbToLinear(g);
  const bLin = sRgbToLinear(b);
  return 0.2126 * rLin + 0.7152 * gLin + 0.0722 * bLin;
}

function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

const lightTokens = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../tokens/semantic.light.json'), 'utf-8')
);
const darkTokens = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../tokens/semantic.dark.json'), 'utf-8')
);

describe('WCAG 2.1 AA Contrast Ratio Verification', () => {
  describe('Light Theme Contrast', () => {
    const bgCanvas = lightTokens.color.bg.canvas.$value;
    const bgSurface = lightTokens.color.bg.surface.$value;
    const fgDefault = lightTokens.color.fg.default.$value;
    const fgMuted = lightTokens.color.fg.muted.$value;
    const fgSubtle = lightTokens.color.fg.subtle.$value;
    const fgLink = lightTokens.color.fg.link.$value;
    const actionPrimaryBg = lightTokens.color.action.primary.bg.$value;
    const actionPrimaryFg = lightTokens.color.action.primary.fg.$value;
    const borderStrong = lightTokens.color.border.strong.$value;
    const emergencyBg = lightTokens.color.emergency.bg.$value;
    const emergencyFg = lightTokens.color.emergency.fg.$value;

    it('fg.default on bg.canvas achieves >= 4.5:1 (actual: >16:1)', () => {
      const ratio = contrastRatio(fgDefault, bgCanvas);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.default on bg.surface achieves >= 4.5:1', () => {
      const ratio = contrastRatio(fgDefault, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.muted on bg.surface achieves >= 4.5:1', () => {
      const ratio = contrastRatio(fgMuted, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.subtle on bg.surface achieves >= 4.5:1', () => {
      const ratio = contrastRatio(fgSubtle, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.link on bg.surface achieves >= 4.5:1', () => {
      const ratio = contrastRatio(fgLink, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('action.primary.fg on action.primary.bg achieves >= 4.5:1', () => {
      const ratio = contrastRatio(actionPrimaryFg, actionPrimaryBg);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('emergency.fg on emergency.bg achieves >= 4.5:1', () => {
      const ratio = contrastRatio(emergencyFg, emergencyBg);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('border.strong on bg.surface achieves >= 3:1 non-text contrast', () => {
      const ratio = contrastRatio(borderStrong, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });
  });

  describe('Dark Theme Contrast', () => {
    const bgCanvas = darkTokens.color.bg.canvas.$value;
    const bgSurface = darkTokens.color.bg.surface.$value;
    const fgDefault = darkTokens.color.fg.default.$value;
    const fgMuted = darkTokens.color.fg.muted.$value;
    const fgSubtle = darkTokens.color.fg.subtle.$value;
    const actionPrimaryBg = darkTokens.color.action.primary.bg.$value;
    const actionPrimaryFg = darkTokens.color.action.primary.fg.$value;
    const borderStrong = darkTokens.color.border.strong.$value;
    const emergencyBg = darkTokens.color.emergency.bg.$value;
    const emergencyFg = darkTokens.color.emergency.fg.$value;

    it('fg.default on bg.canvas achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(fgDefault, bgCanvas);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.default on bg.surface achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(fgDefault, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.muted on bg.surface achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(fgMuted, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('fg.subtle on bg.surface achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(fgSubtle, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('action.primary.fg on action.primary.bg achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(actionPrimaryFg, actionPrimaryBg);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('emergency.fg on emergency.bg achieves >= 4.5:1 in dark mode', () => {
      const ratio = contrastRatio(emergencyFg, emergencyBg);
      expect(ratio).toBeGreaterThanOrEqual(4.5);
    });

    it('border.strong on bg.surface achieves >= 3:1 non-text contrast in dark mode', () => {
      const ratio = contrastRatio(borderStrong, bgSurface);
      expect(ratio).toBeGreaterThanOrEqual(3.0);
    });
  });
});
