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

import type { ComponentType } from 'react';

export type SlotId =
  | 'dashboard.card'
  | 'sidebar.item'
  | 'profile.detail'
  | 'chat.messageRenderer'
  | 'chat.composerAction'
  | 'chat.beforeSend'
  | 'settings.section'
  | 'onboarding.step';

export type AudienceBand = 'adult' | 'teen' | 'child' | 'viewer';
export type ScopeId = string;
export type MessageId = string;
export type IconId = string;

export interface SlotProps<P = Record<string, unknown>> {
  profileId: string;
  scopes: ScopeId[];
  density?: 'compact' | 'comfortable';
  extra?: P;
}

export interface SlotContribution<P = Record<string, unknown>> {
  id: string;
  pack: string;
  slot: SlotId;
  title: MessageId;
  icon?: IconId;
  order?: number;
  route?: string;
  requiredScopes: ScopeId[];
  audiences?: AudienceBand[];
  messageKind?: string;
  component?: ComponentType<SlotProps<P>>;
  load?: () => Promise<{ default: ComponentType<SlotProps<P>> }>;
}

export interface PackUi {
  pack: string;
  contributions: SlotContribution[];
  messages?: Record<string, Record<string, string>>;
}

export function definePackUi(def: {
  pack: string;
  contributions: SlotContribution[];
  messages?: Record<string, Record<string, string>>;
}): PackUi {
  return {
    pack: def.pack,
    contributions: def.contributions,
    messages: def.messages,
  };
}

export interface FilterSlotsOptions {
  slot?: SlotId;
  enabledPacks?: string[];
  activeScopes?: string[];
  hiddenPanels?: string[];
  audience?: AudienceBand;
}

export function matchesScopePattern(pattern: string, target: string): boolean {
  if (pattern === '*' || pattern === target) return true;
  if (pattern.endsWith('.*')) {
    const prefix = pattern.slice(0, -2);
    return target === prefix || target.startsWith(`${prefix}.`);
  }
  return false;
}

export function isScopeSatisfied(requiredScope: string, activeScopes: string[]): boolean {
  return activeScopes.some((active) => matchesScopePattern(active, requiredScope));
}

export function filterSlotContributions(
  contributions: SlotContribution[],
  options: FilterSlotsOptions = {}
): SlotContribution[] {
  const { slot, enabledPacks, activeScopes, hiddenPanels = [], audience } = options;

  return contributions
    .filter((c) => {
      if (slot && c.slot !== slot) return false;
      if (enabledPacks && !enabledPacks.includes(c.pack)) return false;
      if (hiddenPanels.includes(c.id)) return false;
      if (audience && c.audiences && c.audiences.length > 0 && !c.audiences.includes(audience)) {
        return false;
      }
      if (activeScopes && c.requiredScopes && c.requiredScopes.length > 0) {
        const allSatisfied = c.requiredScopes.every((req) => isScopeSatisfied(req, activeScopes));
        if (!allSatisfied) return false;
      }
      return true;
    })
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
}
