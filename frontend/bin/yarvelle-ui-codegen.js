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

/**
 * CLI tool: yarvelle-ui-codegen
 * Generates pack-registry.generated.ts based on enabled packs.
 */

import fs from 'node:fs';
import path from 'node:path';

function printHelp() {
  console.log(`Usage: yarvelle-ui-codegen [options]

Options:
  --config <path>    Path to config YAML or JSON (e.g. yarvelle.yaml)
  --packs <list>     Comma-separated list of enabled pack IDs (e.g. finance,education)
  --pack-module <id>=<module>
                     Module that exports the pack's UI as <id>Ui (repeatable,
                     e.g. finance=@acme/finance-ui)
  --out <path>       Output path for pack-registry.generated.ts (default: src/pack-registry.generated.ts)
  --help             Show this help message
`);
}

function parseArgs() {
  const args = process.argv.slice(2);
  let configPath = null;
  let packs = [];
  let outPath = 'src/pack-registry.generated.ts';
  const packUiModules = {};

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--config' && args[i + 1]) {
      configPath = args[++i];
    } else if (args[i] === '--packs' && args[i + 1]) {
      packs = args[++i].split(',').map((p) => p.trim()).filter(Boolean);
    } else if (args[i] === '--pack-module' && args[i + 1]) {
      const [id, ...rest] = args[++i].split('=');
      const specifier = rest.join('=').trim();
      if (id && id.trim() && specifier) packUiModules[id.trim()] = specifier;
    } else if (args[i] === '--out' && args[i + 1]) {
      outPath = args[++i];
    } else if (args[i] === '--help') {
      printHelp();
      process.exit(0);
    }
  }

  if (configPath && fs.existsSync(configPath)) {
    const content = fs.readFileSync(configPath, 'utf-8');
    // Simple regex parse for packs.enabled or YAML list
    const match = content.match(/packs(?:\.enabled)?:\s*\[(.*?)\]/s);
    if (match) {
      const parsed = match[1]
        .split(',')
        .map((s) => s.replace(/['"\s]/g, ''))
        .filter(Boolean);
      if (parsed.length > 0) packs = parsed;
    }
  }

  return { packs, outPath, packUiModules };
}

export function generatePackRegistryCode(packs, packUiModules = {}) {
  const imports = [];
  const packEntries = [];

  for (const pack of packs) {
    const varName = `${pack.replace(/[^a-zA-Z0-9]/g, '_')}Ui`;
    const specifier = packUiModules[pack];
    if (specifier) {
      imports.push(`import { ${varName} } from '${specifier}';`);
      packEntries.push(`  ${JSON.stringify(pack)}: ${varName},`);
    } else {
      imports.push(`// Pack ${pack} UI contribution`);
      packEntries.push(`  // ${pack}: ${varName},`);
    }
  }

  return `// Emitted automatically by yarvelle-ui-codegen — DO NOT EDIT DIRECTLY
import type { PackUi, SlotContribution } from '@yarvelle/ui/slots';
${imports.join('\n')}

export const ENABLED_PACKS: string[] = ${JSON.stringify(packs, null, 2)};

export const PACK_REGISTRY: Record<string, PackUi | undefined> = {
${packEntries.join('\n')}
};

export function getAllSlotContributions(): SlotContribution[] {
  const result: SlotContribution[] = [];
  for (const packId of ENABLED_PACKS) {
    const pack = PACK_REGISTRY[packId];
    if (pack?.contributions) {
      result.push(...pack.contributions);
    }
  }
  return result;
}
`;
}

function main() {
  const { packs, outPath, packUiModules } = parseArgs();
  const finalPacks = packs;
  const code = generatePackRegistryCode(finalPacks, packUiModules);
  const resolvedOut = path.resolve(process.cwd(), outPath);
  fs.mkdirSync(path.dirname(resolvedOut), { recursive: true });
  fs.writeFileSync(resolvedOut, code);
  console.log(`Generated pack registry for [${finalPacks.join(', ')}] at ${resolvedOut}`);
}

main();
