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

import { Calendar } from '../src/index.js';
import type { CalendarEvent, CalendarViewMode } from '../src/calendar/types.js';

describe('E2E Calendar View & Date Filtering Suite (Issue #67)', () => {
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

  const sampleEvents: CalendarEvent[] = [
    {
      id: 'event-1',
      title: 'Sprint Planning Sync',
      start: '2026-11-16T09:00:00Z',
      end: '2026-11-16T10:00:00Z',
      location: 'Virtual Room A',
      conflict: false,
    },
    {
      id: 'event-2',
      title: 'Operations Review',
      start: '2026-11-18T14:00:00Z',
      end: '2026-11-18T15:00:00Z',
      location: 'Virtual Room B',
      conflict: true,
    },
    {
      id: 'event-3',
      title: 'Infrastructure Maintenance',
      start: '2026-11-20T11:00:00Z',
      end: '2026-11-20T12:00:00Z',
      conflict: false,
    },
  ];

  it('renders Calendar in month view by default with day headers and toolbar', async () => {
    await renderComponent(
      <Calendar
        events={sampleEvents}
        selectedDate={new Date('2026-11-15T12:00:00Z')}
      />
    );

    const rootElement = container.querySelector('[data-slot="calendar"]');
    expect(rootElement).not.toBeNull();
    expect(rootElement?.getAttribute('data-view')).toBe('month');

    const monthView = container.querySelector('[data-slot="month-view"]');
    expect(monthView).not.toBeNull();

    // Verify weekday headers
    expect(container.textContent).toContain('Sun');
    expect(container.textContent).toContain('Mon');
    expect(container.textContent).toContain('Tue');
    expect(container.textContent).toContain('Wed');
    expect(container.textContent).toContain('Thu');
    expect(container.textContent).toContain('Fri');
    expect(container.textContent).toContain('Sat');
  });

  it('renders Calendar in week view mode with 7-day columns', async () => {
    await renderComponent(
      <Calendar
        events={sampleEvents}
        selectedDate={new Date('2026-11-15T12:00:00Z')}
        viewMode="week"
      />
    );

    const weekView = container.querySelector('[data-slot="week-view"]');
    expect(weekView).not.toBeNull();

    const rootElement = container.querySelector('[data-slot="calendar"]');
    expect(rootElement?.getAttribute('data-view')).toBe('week');

    // Week view contains 7 day column cards
    const dayColumns = weekView?.querySelectorAll('.rounded-lg');
    expect(dayColumns?.length).toBe(7);

    // Verify events appear strictly on their corresponding day of the week
    // Sunday (col 0): no events
    expect(dayColumns?.[0]?.textContent).toContain('Sun');
    expect(dayColumns?.[0]?.textContent).not.toContain('Sprint Planning Sync');
    expect(dayColumns?.[0]?.textContent).not.toContain('Operations Review');

    // Monday (col 1): Sprint Planning Sync (2026-11-16)
    expect(dayColumns?.[1]?.textContent).toContain('Mon');
    expect(dayColumns?.[1]?.textContent).toContain('Sprint Planning Sync');
    expect(dayColumns?.[1]?.textContent).not.toContain('Operations Review');

    // Tuesday (col 2): no events
    expect(dayColumns?.[2]?.textContent).toContain('Tue');
    expect(dayColumns?.[2]?.textContent).not.toContain('Sprint Planning Sync');

    // Wednesday (col 3): Operations Review (2026-11-18)
    expect(dayColumns?.[3]?.textContent).toContain('Wed');
    expect(dayColumns?.[3]?.textContent).toContain('Operations Review');
    expect(dayColumns?.[3]?.textContent).not.toContain('Sprint Planning Sync');

    // Friday (col 5): Infrastructure Maintenance (2026-11-20)
    expect(dayColumns?.[5]?.textContent).toContain('Fri');
    expect(dayColumns?.[5]?.textContent).toContain('Infrastructure Maintenance');
  });

  it('renders Calendar in agenda view and displays event metadata and conflict badge', async () => {
    const onSelectEvent = vi.fn();
    await renderComponent(
      <Calendar
        events={sampleEvents}
        selectedDate={new Date('2026-11-15T12:00:00Z')}
        viewMode="agenda"
        onSelectEvent={onSelectEvent}
      />
    );

    const agendaView = container.querySelector('[data-slot="agenda-view"]');
    expect(agendaView).not.toBeNull();

    expect(container.textContent).toContain('Sprint Planning Sync');
    expect(container.textContent).toContain('Virtual Room A');
    expect(container.textContent).toContain('Operations Review');
    expect(container.textContent).toContain('Conflict');

    // Clicking an event triggers onSelectEvent
    const firstEvent = agendaView?.querySelector('.cursor-pointer');
    expect(firstEvent).not.toBeNull();
    act(() => {
      (firstEvent as HTMLElement)?.click();
    });
    expect(onSelectEvent).toHaveBeenCalledTimes(1);
    expect(onSelectEvent).toHaveBeenCalledWith(sampleEvents[0]);
  });

  it('handles navigation controls (Today, Next, Previous)', async () => {
    const onSelectDate = vi.fn();
    await renderComponent(
      <Calendar
        events={sampleEvents}
        selectedDate={new Date('2026-11-15T12:00:00Z')}
        onSelectDate={onSelectDate}
      />
    );

    const todayButton = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Today')
    );
    expect(todayButton).toBeDefined();

    act(() => {
      todayButton?.click();
    });
    expect(onSelectDate).toHaveBeenCalled();

    const nextButton = container.querySelector('button[aria-label="Next"]');
    expect(nextButton).not.toBeNull();
    act(() => {
      (nextButton as HTMLElement)?.click();
    });
    expect(onSelectDate).toHaveBeenCalled();

    const prevButton = container.querySelector('button[aria-label="Previous"]');
    expect(prevButton).not.toBeNull();
    act(() => {
      (prevButton as HTMLElement)?.click();
    });
    expect(onSelectDate).toHaveBeenCalled();
  });

  it('displays empty state in agenda view when events list is empty', async () => {
    await renderComponent(
      <Calendar
        events={[]}
        selectedDate={new Date('2026-11-15T12:00:00Z')}
        viewMode="agenda"
      />
    );

    expect(container.textContent).toContain('No scheduled events.');
  });
});
