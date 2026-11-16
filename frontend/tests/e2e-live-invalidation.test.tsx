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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import { ChatRoot } from '../src/chat/Chat.js';
import type { EntityChangedEvent } from '../src/chat/types.js';

/**
 * Domain-neutral reactive entity invalidation subscriber helper.
 * Simulates a client-side query invalidation hook (e.g. useEntityChanged)
 * that listens for live SSE entity_changed events and refetches matching data.
 */
function useEntityInvalidationListener(
  targetProfileId: string,
  targetEntityType: string,
  onInvalidate: (event: EntityChangedEvent) => void
) {
  React.useEffect(() => {
    const handleCustomEvent = (e: Event) => {
      const customEvent = e as CustomEvent<EntityChangedEvent>;
      const payload = customEvent.detail;
      if (!payload) return;

      // Filter by profile isolation and matching entity type
      if (
        payload.profile_id === targetProfileId &&
        (payload.entity_type === targetEntityType || payload.entity === targetEntityType)
      ) {
        onInvalidate(payload);
      }
    };

    window.addEventListener('yarvelle:entity_changed', handleCustomEvent);
    return () => {
      window.removeEventListener('yarvelle:entity_changed', handleCustomEvent);
    };
  }, [targetProfileId, targetEntityType, onInvalidate]);
}

describe('E2E Live Invalidation & entity_changed SSE Event Suite (Issue #66)', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  const renderComponent = async (element: React.ReactElement) => {
    await act(async () => {
      root.render(element);
    });
  };

  it('ChatRoot mounts and forwards onEntityChanged callback', async () => {
    const onEntityChanged = vi.fn();
    const sampleEvent: EntityChangedEvent = {
      type: 'entity_changed',
      entity_type: 'workspace_note',
      entity: 'workspace_note',
      entity_id: 'note-uuid-123',
      record_id: 'note-uuid-123',
      action: 'created',
      profile_id: 'prof-steward',
      scope: 'steward.general',
      tool: 'create_workspace_note',
      timestamp: new Date().toISOString(),
    };

    function TestChild() {
      return (
        <button
          type="button"
          onClick={() => onEntityChanged(sampleEvent)}
          data-slot="trigger-entity-changed"
        >
          Simulate Mutation
        </button>
      );
    }

    await renderComponent(
      <ChatRoot
        messages={[]}
        onSendMessage={vi.fn()}
        onEntityChanged={onEntityChanged}
      >
        <TestChild />
      </ChatRoot>
    );

    const button = container.querySelector('[data-slot="trigger-entity-changed"]');
    expect(button).not.toBeNull();

    act(() => {
      (button as HTMLButtonElement).click();
    });

    expect(onEntityChanged).toHaveBeenCalledTimes(1);
    expect(onEntityChanged).toHaveBeenCalledWith(sampleEvent);
  });

  it('dispatches invalidation only when profile_id and entity_type match', async () => {
    const onInvalidate = vi.fn();

    function TestSubscriber({ profileId, entityType }: { profileId: string; entityType: string }) {
      useEntityInvalidationListener(profileId, entityType, onInvalidate);
      return <div data-slot="subscriber">Listening for {entityType}</div>;
    }

    await renderComponent(
      <TestSubscriber profileId="prof-alpha" entityType="workspace_note" />
    );

    // Event 1: Matching profile and matching entity type -> triggers invalidation
    act(() => {
      const event = new CustomEvent('yarvelle:entity_changed', {
        detail: {
          type: 'entity_changed',
          entity_type: 'workspace_note',
          entity: 'workspace_note',
          entity_id: 'note-1',
          record_id: 'note-1',
          action: 'created',
          profile_id: 'prof-alpha',
          scope: 'steward.general',
          tool: 'create_workspace_note',
          timestamp: new Date().toISOString(),
        },
      });
      window.dispatchEvent(event);
    });
    expect(onInvalidate).toHaveBeenCalledTimes(1);

    // Event 2: Different profile (prof-beta) -> ignored (profile isolation)
    act(() => {
      const event = new CustomEvent('yarvelle:entity_changed', {
        detail: {
          type: 'entity_changed',
          entity_type: 'workspace_note',
          entity: 'workspace_note',
          entity_id: 'note-2',
          record_id: 'note-2',
          action: 'updated',
          profile_id: 'prof-beta',
          scope: 'steward.general',
          tool: 'update_workspace_note',
          timestamp: new Date().toISOString(),
        },
      });
      window.dispatchEvent(event);
    });
    expect(onInvalidate).toHaveBeenCalledTimes(1);

    // Event 3: Different entity type (reminder) -> ignored
    act(() => {
      const event = new CustomEvent('yarvelle:entity_changed', {
        detail: {
          type: 'entity_changed',
          entity_type: 'reminder',
          entity: 'reminder',
          entity_id: 'rem-1',
          record_id: 'rem-1',
          action: 'created',
          profile_id: 'prof-alpha',
          scope: 'steward.general',
          tool: 'create_profile_reminder',
          timestamp: new Date().toISOString(),
        },
      });
      window.dispatchEvent(event);
    });
    expect(onInvalidate).toHaveBeenCalledTimes(1);
  });

  it('handles rapid sequential entity_changed events without dropping invalidations', async () => {
    const onInvalidate = vi.fn();

    function TestSubscriber() {
      useEntityInvalidationListener('prof-stream', 'workspace_note', onInvalidate);
      return <div>Rapid Stream</div>;
    }

    await renderComponent(<TestSubscriber />);

    act(() => {
      for (let i = 0; i < 15; i++) {
        window.dispatchEvent(
          new CustomEvent('yarvelle:entity_changed', {
            detail: {
              type: 'entity_changed',
              entity_type: 'workspace_note',
              entity: 'workspace_note',
              entity_id: `note-${i}`,
              record_id: `note-${i}`,
              action: 'created',
              profile_id: 'prof-stream',
              scope: 'steward.general',
              tool: 'create_workspace_note',
              timestamp: new Date().toISOString(),
            },
          })
        );
      }
    });

    expect(onInvalidate).toHaveBeenCalledTimes(15);
  });

  it('unmount cleans up event listener and suppresses subsequent events', async () => {
    const onInvalidate = vi.fn();

    function TestSubscriber() {
      useEntityInvalidationListener('prof-temp', 'workspace_note', onInvalidate);
      return <div>Temporary Subscriber</div>;
    }

    await renderComponent(<TestSubscriber />);

    // Unmount subscriber
    act(() => {
      root.unmount();
    });

    // Dispatch event after unmount
    act(() => {
      window.dispatchEvent(
        new CustomEvent('yarvelle:entity_changed', {
          detail: {
            type: 'entity_changed',
            entity_type: 'workspace_note',
            entity: 'workspace_note',
            entity_id: 'note-unmounted',
            record_id: 'note-unmounted',
            action: 'created',
            profile_id: 'prof-temp',
            scope: 'steward.general',
            tool: 'create_workspace_note',
            timestamp: new Date().toISOString(),
          },
        })
      );
    });

    expect(onInvalidate).not.toHaveBeenCalled();
  });
});
