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
import {
  definePackUi,
  filterSlotContributions,
  matchesScopePattern,
  isScopeSatisfied,
  type SlotContribution,
} from '../src/slots/types.js';

describe('Slot Registry & Scope Matching', () => {
  it('matches wildcard and prefixed scope patterns correctly', () => {
    expect(matchesScopePattern('*', 'health.records')).toBe(true);
    expect(matchesScopePattern('health.*', 'health.records')).toBe(true);
    expect(matchesScopePattern('health.*', 'health.prescriptions.active')).toBe(true);
    expect(matchesScopePattern('health.*', 'finance.bills')).toBe(false);
    expect(matchesScopePattern('general', 'general')).toBe(true);
    expect(matchesScopePattern('general', 'other')).toBe(false);
  });

  it('checks if required scopes are satisfied by active scopes', () => {
    const active = ['health.*', 'finance.read'];
    expect(isScopeSatisfied('health.records', active)).toBe(true);
    expect(isScopeSatisfied('finance.read', active)).toBe(true);
    expect(isScopeSatisfied('finance.write', active)).toBe(false);
  });

  it('filters slot contributions by slot id, enabled packs, scopes, and audiences', () => {
    const mockContributions: SlotContribution[] = [
      {
        id: 'c1',
        pack: 'pack-a',
        slot: 'dashboard.card',
        title: 'Card A',
        requiredScopes: ['notes.read'],
        audiences: ['adult', 'teen'],
        order: 20,
      },
      {
        id: 'c2',
        pack: 'pack-b',
        slot: 'dashboard.card',
        title: 'Card B',
        requiredScopes: ['records.*'],
        audiences: ['adult'],
        order: 10,
      },
      {
        id: 'c3',
        pack: 'pack-a',
        slot: 'sidebar.item',
        title: 'Sidebar A',
        requiredScopes: [],
        order: 5,
      },
    ];

    // Filter by slot
    const cards = filterSlotContributions(mockContributions, { slot: 'dashboard.card' });
    expect(cards.length).toBe(2);
    // Verified sorting by order: c2 (order 10) should come before c1 (order 20)
    expect(cards[0].id).toBe('c2');
    expect(cards[1].id).toBe('c1');

    // Filter by audience
    const teenCards = filterSlotContributions(mockContributions, {
      slot: 'dashboard.card',
      audience: 'teen',
    });
    expect(teenCards.map((c) => c.id)).toEqual(['c1']);

    // Filter by hiddenPanels
    const withoutC2 = filterSlotContributions(mockContributions, {
      slot: 'dashboard.card',
      hiddenPanels: ['c2'],
    });
    expect(withoutC2.map((c) => c.id)).toEqual(['c1']);

    // Filter by unsatisfied scopes
    const satisfied = filterSlotContributions(mockContributions, {
      slot: 'dashboard.card',
      activeScopes: ['notes.read'],
    });
    expect(satisfied.map((c) => c.id)).toEqual(['c1']);
  });

  it('creates PackUi definition using definePackUi', () => {
    const packUi = definePackUi({
      pack: 'demo-pack',
      contributions: [
        {
          id: 'slot-1',
          pack: 'demo-pack',
          slot: 'dashboard.card',
          title: 'Demo Card',
          requiredScopes: ['general'],
        },
      ],
      messages: {
        'en-US': { 'demo.card.title': 'Demo Card' },
      },
    });

    expect(packUi.pack).toBe('demo-pack');
    expect(packUi.contributions.length).toBe(1);
    expect(packUi.messages?.['en-US']['demo.card.title']).toBe('Demo Card');
  });
});
