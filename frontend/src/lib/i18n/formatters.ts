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

export function getTextDirection(locale: string): 'ltr' | 'rtl' {
  const rtlLocales = ['ar', 'he', 'fa', 'ur', 'ar-SA', 'he-IL'];
  const prefix = locale.split('-')[0].toLowerCase();
  return rtlLocales.includes(locale) || rtlLocales.includes(prefix) ? 'rtl' : 'ltr';
}

export function formatDate(
  value: Date | string | number,
  locale: string = 'en-US',
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' }
): string {
  const d = typeof value === 'object' ? value : new Date(value);
  try {
    return new Intl.DateTimeFormat(locale, options).format(d);
  } catch {
    return d.toLocaleDateString();
  }
}

export function formatTime(
  value: Date | string | number,
  locale: string = 'en-US',
  options: Intl.DateTimeFormatOptions = { timeStyle: 'short' }
): string {
  const d = typeof value === 'object' ? value : new Date(value);
  try {
    return new Intl.DateTimeFormat(locale, options).format(d);
  } catch {
    return d.toLocaleTimeString();
  }
}

export function formatDateTime(
  value: Date | string | number,
  locale: string = 'en-US',
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' }
): string {
  const d = typeof value === 'object' ? value : new Date(value);
  try {
    return new Intl.DateTimeFormat(locale, options).format(d);
  } catch {
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
  }
}

export function formatNumber(
  value: number,
  locale: string = 'en-US',
  options: Intl.NumberFormatOptions = {}
): string {
  try {
    return new Intl.NumberFormat(locale, options).format(value);
  } catch {
    return String(value);
  }
}
