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

const DIST_GLOB_SUFFIX = 'dist/**/*.{js,mjs}';

function normalizePosixPath(input: string): string {
  const forward = input.trim().replace(/\\/g, '/');
  if (forward === '/') {
    return '/';
  }
  return forward.replace(/\/+$/, '');
}

function resolveSelfPackageRoot(): string | null {
  try {
    const metaUrl = import.meta.url;
    if (!metaUrl || !metaUrl.startsWith('file:')) {
      return null;
    }
    let pathname = decodeURIComponent(new URL(metaUrl).pathname).replace(/\\/g, '/');
    // Strip leading slash before Windows drive letters (e.g. "/C:/app/..." -> "C:/app/...")
    if (/^\/[A-Za-z]:\//.test(pathname)) {
      pathname = pathname.slice(1);
    }
    const distIdx = pathname.lastIndexOf('/dist/');
    if (distIdx !== -1) {
      return pathname.slice(0, distIdx);
    }
    const srcIdx = pathname.lastIndexOf('/src/');
    if (srcIdx !== -1) {
      return pathname.slice(0, srcIdx);
    }
  } catch {
    // Fall through to relative node_modules fallback in non-standard bundler contexts
  }
  return null;
}

/**
 * Returns a POSIX-normalized Tailwind CSS `content` glob covering `@yarvelle/ui`'s
 * compiled ESM bundles (`dist/**\/*.{js,mjs}`).
 *
 * - Called with no arguments (`yarvelleUiContentGlob()`), resolves the installed
 *   `@yarvelle/ui` package directory directly from `import.meta.url`, working across
 *   npm, pnpm virtual stores, Yarn workspaces, and hoisted monorepos.
 * - Called with `rootDir` (`yarvelleUiContentGlob(appRoot)`), builds a normalized
 *   POSIX glob rooted at `rootDir` (`<rootDir>/node_modules/@yarvelle/ui/dist/**\/*.{js,mjs}`,
 *   or `<rootDir>/dist/**\/*.{js,mjs}` when `rootDir` already points at `@yarvelle/ui`).
 */
export function yarvelleUiContentGlob(rootDir?: string): string {
  if (typeof rootDir === 'string' && rootDir.trim().length > 0) {
    const normalized = normalizePosixPath(rootDir);
    if (normalized.endsWith('/@yarvelle/ui/dist') || normalized === 'dist' || normalized === './dist') {
      return `${normalized}/**/*.{js,mjs}`;
    }
    if (normalized.endsWith('/@yarvelle/ui')) {
      return `${normalized}/${DIST_GLOB_SUFFIX}`;
    }
    const prefix = normalized === '/' ? '' : normalized;
    return `${prefix}/node_modules/@yarvelle/ui/${DIST_GLOB_SUFFIX}`;
  }

  const selfRoot = resolveSelfPackageRoot();
  if (selfRoot) {
    return `${selfRoot}/${DIST_GLOB_SUFFIX}`;
  }

  return `./node_modules/@yarvelle/ui/${DIST_GLOB_SUFFIX}`;
}
