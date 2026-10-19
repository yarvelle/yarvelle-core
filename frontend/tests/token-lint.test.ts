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

function getAllSourceFiles(dir: string, fileList: string[] = []): string[] {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      getAllSourceFiles(fullPath, fileList);
    } else if (file.endsWith('.ts') || file.endsWith('.tsx')) {
      fileList.push(fullPath);
    }
  }
  return fileList;
}

const srcDir = path.resolve(__dirname, '../src');
const sourceFiles = getAllSourceFiles(srcDir);

describe('GU3 Token Lint & Architectural Purity', () => {
  it('contains zero raw Tailwind palette classes in src/**', () => {
    // e.g. bg-zinc-500, text-slate-900, border-blue-200
    const palettePattern = /\b(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]{2,3}\b/g;
    const violations: Array<{ file: string; match: string }> = [];

    for (const filePath of sourceFiles) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const matches = content.match(palettePattern);
      if (matches) {
        matches.forEach((m) => violations.push({ file: path.relative(srcDir, filePath), match: m }));
      }
    }

    expect(violations).toEqual([]);
  });

  it('contains zero hardcoded #hex colors in TypeScript source code', () => {
    // Only tokens.css may contain hex; src/**/*.ts(x) must use CSS variables or semantic classes
    const hexPattern = /#[0-9a-fA-F]{3,8}\b/g;
    const violations: Array<{ file: string; match: string }> = [];

    for (const filePath of sourceFiles) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const matches = content.match(hexPattern);
      if (matches) {
        matches.forEach((m) => violations.push({ file: path.relative(srcDir, filePath), match: m }));
      }
    }

    expect(violations).toEqual([]);
  });

  it('contains zero dark: Tailwind variant classes in components', () => {
    const darkVariantPattern = /\bdark:/g;
    const violations: Array<{ file: string; match: string }> = [];

    for (const filePath of sourceFiles) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const matches = content.match(darkVariantPattern);
      if (matches) {
        matches.forEach((m) => violations.push({ file: path.relative(srcDir, filePath), match: m }));
      }
    }

    expect(violations).toEqual([]);
  });

  it('contains zero physical-direction classes (ms-, me-, ps-, pe-, start-, end- only)', () => {
    // Physical classes: ml-, mr-, pl-, pr-, left-, right-
    // Note: ignore comments and words like 'split', 'plural', 'replace' by checking for class context
    const physicalPattern = /\b(ml-|mr-|pl-|pr-|left-[0-9]|right-[0-9]|left-0|right-0|left-1|right-1|left-2|right-2|left-3|right-3|left-4|right-4)\b/g;
    const violations: Array<{ file: string; match: string }> = [];

    for (const filePath of sourceFiles) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const matches = content.match(physicalPattern);
      if (matches) {
        matches.forEach((m) => violations.push({ file: path.relative(srcDir, filePath), match: m }));
      }
    }

    expect(violations).toEqual([]);
  });

  it('contains zero domain/clinical/product keywords in domain-neutral @yarvelle/ui', () => {
    // Domain words prohibited in @yarvelle/ui: patient, doctor, clinical, vitals, nurse, hospital, physician, prescription
    const domainWords = [
      'patient',
      'doctor',
      'clinical',
      'vitals',
      'nurse',
      'hospital',
      'physician',
      'prescription',
      'carefold',
    ];
    const domainPattern = new RegExp(`\\b(${domainWords.join('|')})\\b`, 'gi');
    const violations: Array<{ file: string; match: string }> = [];

    for (const filePath of sourceFiles) {
      const content = fs.readFileSync(filePath, 'utf-8');
      const matches = content.match(domainPattern);
      if (matches) {
        matches.forEach((m) => violations.push({ file: path.relative(srcDir, filePath), match: m }));
      }
    }

    expect(violations).toEqual([]);
  });
});
