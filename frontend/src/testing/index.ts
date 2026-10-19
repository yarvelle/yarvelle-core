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

import * as React from 'react';
import type { SlotContribution, SlotProps } from '../slots/types.js';
import type { ProfileMember } from '../profiles/types.js';
import type { ChatMessage } from '../chat/types.js';

export function createMockSlotContribution(
  overrides?: Partial<SlotContribution>
): SlotContribution {
  return {
    id: 'test-slot-1',
    pack: 'test-pack',
    slot: 'dashboard.card',
    title: 'Test Card',
    requiredScopes: ['general'],
    order: 10,
    ...overrides,
  };
}

export function createMockProfile(
  overrides?: Partial<ProfileMember>
): ProfileMember {
  return {
    id: 'profile-1',
    displayName: 'Primary User',
    role: 'owner',
    scopes: ['general', 'notes', 'calendar'],
    ...overrides,
  };
}

export function createMockChatMessage(
  overrides?: Partial<ChatMessage>
): ChatMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content: 'Hello, world!',
    createdAt: '12:00 PM',
    ...overrides,
  };
}
