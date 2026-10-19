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
import { cn } from '../lib/cn.js';
import { Button } from '../primitives/Button.js';
import { Badge } from '../primitives/Badge.js';
import { SegmentedControl } from '../primitives/Segmented.js';
import type { CalendarEvent, CalendarViewMode } from './types.js';

export interface CalendarProps {
  events: CalendarEvent[];
  selectedDate?: Date;
  onSelectDate?: (date: Date) => void;
  onSelectEvent?: (event: CalendarEvent) => void;
  viewMode?: CalendarViewMode;
  onViewModeChange?: (view: CalendarViewMode) => void;
  className?: string;
}

export function Calendar({
  events,
  selectedDate = new Date(),
  onSelectDate,
  onSelectEvent,
  viewMode = 'month',
  onViewModeChange,
  className,
}: CalendarProps) {
  const [currentDate, setCurrentDate] = React.useState<Date>(selectedDate);
  const [currentView, setCurrentView] = React.useState<CalendarViewMode>(viewMode);

  const activeView = onViewModeChange ? viewMode : currentView;
  const setView = (v: CalendarViewMode) => {
    setCurrentView(v);
    onViewModeChange?.(v);
  };

  const handlePrev = () => {
    const next = new Date(currentDate);
    if (activeView === 'month') {
      next.setMonth(next.getMonth() - 1);
    } else if (activeView === 'week') {
      next.setDate(next.getDate() - 7);
    } else {
      next.setDate(next.getDate() - 1);
    }
    setCurrentDate(next);
    onSelectDate?.(next);
  };

  const handleNext = () => {
    const next = new Date(currentDate);
    if (activeView === 'month') {
      next.setMonth(next.getMonth() + 1);
    } else if (activeView === 'week') {
      next.setDate(next.getDate() + 7);
    } else {
      next.setDate(next.getDate() + 1);
    }
    setCurrentDate(next);
    onSelectDate?.(next);
  };

  const handleToday = () => {
    const today = new Date();
    setCurrentDate(today);
    onSelectDate?.(today);
  };

  const monthName = currentDate.toLocaleString('default', { month: 'long', year: 'numeric' });

  // Generate days in month for month view
  const monthDays = React.useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    const firstDayIndex = new Date(year, month, 1).getDay();
    const daysCount = new Date(year, month + 1, 0).getDate();

    const days: Array<{ dayNumber: number; date: Date; isCurrentMonth: boolean }> = [];

    // Leading days from previous month
    const prevMonthDaysCount = new Date(year, month, 0).getDate();
    for (let i = firstDayIndex - 1; i >= 0; i--) {
      days.push({
        dayNumber: prevMonthDaysCount - i,
        date: new Date(year, month - 1, prevMonthDaysCount - i),
        isCurrentMonth: false,
      });
    }

    // Days in current month
    for (let i = 1; i <= daysCount; i++) {
      days.push({
        dayNumber: i,
        date: new Date(year, month, i),
        isCurrentMonth: true,
      });
    }

    return days;
  }, [currentDate]);

  return (
    <div
      data-slot="calendar"
      data-view={activeView}
      className={cn(
        'yc-Calendar-root flex flex-col rounded-xl border border-border bg-surface p-4 shadow-1',
        className
      )}
    >
      {/* Header toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-fg">{monthName}</h2>
          <Button size="sm" variant="outline" onClick={handleToday}>
            Today
          </Button>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="ghost" onClick={handlePrev} aria-label="Previous">
              ‹
            </Button>
            <Button size="sm" variant="ghost" onClick={handleNext} aria-label="Next">
              ›
            </Button>
          </div>
        </div>

        <SegmentedControl
          size="sm"
          value={activeView}
          onChange={(v) => setView(v as CalendarViewMode)}
          options={[
            { value: 'month', label: 'Month' },
            { value: 'week', label: 'Week' },
            { value: 'agenda', label: 'Agenda' },
          ]}
        />
      </div>

      {/* Main views */}
      {activeView === 'month' && (
        <div data-slot="month-view" className="mt-4 flex flex-col">
          {/* Weekday headers */}
          <div className="grid grid-cols-7 text-center text-xs font-semibold text-fg-muted pb-2">
            {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
              <div key={d} className="py-1">
                {d}
              </div>
            ))}
          </div>

          {/* Month grid */}
          <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden border border-border">
            {monthDays.map((d, idx) => {
              const dateStr = d.date.toISOString().split('T')[0];
              const dayEvents = events.filter((e) => {
                const s = typeof e.start === 'string' ? e.start : e.start.toISOString();
                return s.startsWith(dateStr);
              });
              const hasConflict = dayEvents.some((e) => e.conflict);

              return (
                <div
                  key={idx}
                  onClick={() => onSelectDate?.(d.date)}
                  className={cn(
                    'min-h-[80px] p-1.5 flex flex-col justify-between cursor-pointer transition-colors',
                    d.isCurrentMonth ? 'bg-surface hover:bg-surface-2' : 'bg-surface-2/50 text-fg-muted'
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">{d.dayNumber}</span>
                    {hasConflict && (
                      <Badge variant="danger" className="text-[10px] px-1 py-0">
                        Conflict
                      </Badge>
                    )}
                  </div>

                  <div className="flex flex-col gap-1 mt-1">
                    {dayEvents.slice(0, 2).map((ev) => (
                      <button
                        key={ev.id}
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectEvent?.(ev);
                        }}
                        className={cn(
                          'truncate rounded px-1 text-[11px] text-start font-medium',
                          ev.conflict ? 'bg-danger-bg text-danger-fg' : 'bg-primary-subtle text-primary'
                        )}
                      >
                        {ev.title}
                      </button>
                    ))}
                    {dayEvents.length > 2 && (
                      <span className="text-[10px] text-fg-muted ps-1">
                        +{dayEvents.length - 2} more
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {activeView === 'week' && (
        <div data-slot="week-view" className="mt-4 p-4 text-center text-sm text-fg-muted">
          <div className="grid grid-cols-7 gap-2">
            {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((dayName, idx) => (
              <div key={idx} className="rounded-lg border border-border p-2 bg-surface-2">
                <div className="font-semibold text-fg text-xs pb-1">{dayName}</div>
                <div className="space-y-1 mt-2">
                  {events.slice(0, 2).map((ev) => (
                    <div
                      key={ev.id}
                      onClick={() => onSelectEvent?.(ev)}
                      className={cn(
                        'cursor-pointer rounded p-1 text-[11px] truncate text-start',
                        ev.conflict ? 'bg-danger-bg text-danger-fg' : 'bg-surface text-fg shadow-1'
                      )}
                    >
                      {ev.title}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeView === 'agenda' && (
        <div data-slot="agenda-view" className="mt-4 flex flex-col gap-2">
          {events.length === 0 ? (
            <div className="py-8 text-center text-sm text-fg-muted">No scheduled events.</div>
          ) : (
            events.map((ev) => (
              <div
                key={ev.id}
                onClick={() => onSelectEvent?.(ev)}
                className={cn(
                  'flex items-center justify-between rounded-lg border p-3 cursor-pointer hover:bg-surface-2 transition-colors',
                  ev.conflict ? 'border-danger-border bg-danger-bg/20' : 'border-border bg-surface'
                )}
              >
                <div>
                  <h4 className="text-sm font-semibold text-fg">{ev.title}</h4>
                  <p className="text-xs text-fg-muted">
                    {String(ev.start)} {ev.location && `• ${ev.location}`}
                  </p>
                </div>
                {ev.conflict && <Badge variant="danger">Conflict</Badge>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
