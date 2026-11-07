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

const pkgDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(pkgDir, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf-8'));

const LEGAL_FILES = ['LICENSE', 'NOTICE', 'ADDITIONAL-TERMS.md', 'TRADEMARKS.md'];

describe('npm package metadata', () => {
  it('points repository at this GitHub repo and package directory (trusted publishing)', () => {
    expect(pkg.repository).toEqual({
      type: 'git',
      url: 'https://github.com/yarvelle/yarvelle-core',
      directory: 'frontend',
    });
  });

  it('declares public access with provenance', () => {
    expect(pkg.publishConfig).toMatchObject({ access: 'public', provenance: true });
  });

  it('ships the README and legal files', () => {
    expect(fs.existsSync(path.join(pkgDir, 'README.md'))).toBe(true);
    for (const name of ['README.md', ...LEGAL_FILES]) {
      expect(pkg.files).toContain(name);
    }
  });

  it.each(LEGAL_FILES)('keeps %s identical to the repository root copy', (name) => {
    const local = fs.readFileSync(path.join(pkgDir, name), 'utf-8');
    const root = fs.readFileSync(path.join(repoRoot, name), 'utf-8');
    expect(local).toBe(root);
  });

  it('declares the codegen bin in the form npm keeps on publish', () => {
    // npm 11 drops a bin entry written as "./bin/..." during publish.
    expect(pkg.bin).toEqual({ 'yarvelle-ui-codegen': 'bin/yarvelle-ui-codegen.js' });
    expect(fs.existsSync(path.join(pkgDir, pkg.bin['yarvelle-ui-codegen']))).toBe(true);
  });

  it('has contact and discovery metadata', () => {
    expect(pkg.homepage).toMatch(/^https:\/\/github\.com\/yarvelle\/yarvelle-core/);
    expect(pkg.bugs?.url).toBe('https://github.com/yarvelle/yarvelle-core/issues');
    expect(pkg.author?.name).toBe('Spectrayan');
    expect(Array.isArray(pkg.keywords) && pkg.keywords.length).toBeTruthy();
    expect(pkg.engines?.node).toBeTruthy();
  });
});
