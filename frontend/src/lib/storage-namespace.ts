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

export function getStorageKey(namespace: string, key: string, suffix?: string): string {
  const base = `${namespace}_${key}`;
  return suffix ? `${base}_${suffix}` : base;
}

export function getScopedItem(namespace: string, key: string, suffix?: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(getStorageKey(namespace, key, suffix));
  } catch {
    return null;
  }
}

export function setScopedItem(namespace: string, key: string, value: string, suffix?: string): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(getStorageKey(namespace, key, suffix), value);
  } catch {
    // Ignore storage quota errors in sandboxed environments
  }
}

export function removeScopedItem(namespace: string, key: string, suffix?: string): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(getStorageKey(namespace, key, suffix));
  } catch {
    // Ignore errors
  }
}
