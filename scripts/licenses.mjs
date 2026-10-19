#!/usr/bin/env node
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

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..');

const C_BLOCK_HEADER = `/*
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
 */`;

const DOUBLE_SLASH_HEADER = `// Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
// Copyright 2026 Spectrayan (https://spectrayan.com)
//
// Licensed under the PolyForm Noncommercial License 1.0.0 and the
// Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
// Personal and household local use only. Commercial use, hosted service
// offering, rebranding, white-labeling, and redistribution of modified
// forks are prohibited without a written commercial license from Spectrayan.
//
// Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)`;

const HASH_STYLE_HEADER = `# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)`;

const APACHE_MARKER = 'Licensed under the Apache License, Version 2.0';

const TARGET_EXTENSIONS = new Set(['.py', '.ts', '.tsx', '.js', '.mjs', '.css']);

const IGNORED_DIRS = new Set([
  'node_modules',
  'dist',
  '.venv',
  'venv',
  '.git',
  '.pytest_cache',
  'logs',
  '__pycache__',
  '.turbo',
  'build',
  '.changeset',
  '.idea',
  '.import_linter_cache',
]);

const IGNORED_FILES = new Set([
  'next-env.d.ts',
]);

function isPython(filePath) {
  return filePath.endsWith('.py');
}

export function hasLicenseHeader(content, isPy) {
  if (content.includes(APACHE_MARKER)) {
    return true;
  }
  let checkArea = content;
  if (checkArea.startsWith('#!')) {
    const newlineIndex = checkArea.indexOf('\n');
    if (newlineIndex !== -1) {
      checkArea = checkArea.slice(newlineIndex + 1);
    }
  }
  checkArea = checkArea.trimStart();

  const normalizedCheck = checkArea.replace(/\r\n/g, '\n');
  if (isPy) {
    const normalizedExpected = HASH_STYLE_HEADER.replace(/\r\n/g, '\n');
    return normalizedCheck.startsWith(normalizedExpected);
  }

  const normalizedDoubleSlash = DOUBLE_SLASH_HEADER.replace(/\r\n/g, '\n');
  const normalizedCBlock = C_BLOCK_HEADER.replace(/\r\n/g, '\n');
  return (
    normalizedCheck.startsWith(normalizedDoubleSlash) ||
    normalizedCheck.startsWith(normalizedCBlock)
  );
}

function walkDirectory(dir) {
  const results = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (IGNORED_DIRS.has(entry.name)) continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walkDirectory(fullPath));
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name);
      if (TARGET_EXTENSIONS.has(ext) && !IGNORED_FILES.has(entry.name)) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

const args = process.argv.slice(2);
const isCheck = args.includes('check') || args.includes('--check');
const files = walkDirectory(REPO_ROOT);
let hasErrors = false;
let checkedCount = 0;

for (const file of files) {
  checkedCount++;
  const isPy = isPython(file);
  const content = fs.readFileSync(file, 'utf-8');
  if (!hasLicenseHeader(content, isPy)) {
    if (isCheck) {
      console.error(`Missing or invalid license header: ${path.relative(REPO_ROOT, file)}`);
      hasErrors = true;
    }
  }
}

if (isCheck && hasErrors) {
  process.exit(1);
} else if (isCheck) {
  console.log(`All ${checkedCount} files carry compliant license headers (100% compliant).`);
} else {
  console.log(`Checked ${checkedCount} files.`);
}
