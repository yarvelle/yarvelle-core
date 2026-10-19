/*
 * Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

import * as React from 'react';
import { Button } from '../src/primitives/Button.js';
import { Badge } from '../src/primitives/Badge.js';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../src/primitives/Card.js';
import { SegmentedControl } from '../src/primitives/Segmented.js';
import { ApprovalCard } from '../src/chat/ApprovalCard.js';
import { ToolTraceCard } from '../src/chat/ToolTraceCard.js';
import { ExecutionPlanCard } from '../src/chat/ExecutionPlanCard.js';
import { ThinkingIndicator } from '../src/chat/ThinkingIndicator.js';
import { ChatMarkdown } from '../src/chat/ChatMarkdown.js';
import { Calendar } from '../src/calendar/Calendar.js';
import { Reminders } from '../src/calendar/Reminders.js';
import { Routines } from '../src/calendar/Routines.js';
import { ActivityTimeline } from '../src/calendar/ActivityTimeline.js';
import { NotesList } from '../src/notes/NotesList.js';
import { RecordSearch } from '../src/notes/RecordSearch.js';
import { MemberCard } from '../src/profiles/MemberCard.js';
import { RoleMatrix } from '../src/profiles/RoleMatrix.js';
import { TeenHandoverBanner } from '../src/profiles/TeenHandoverBanner.js';
import { TaskList } from '../src/tasks/TaskList.js';
import { NotificationCenter } from '../src/notifications/NotificationCenter.js';
import { AppRail } from '../src/shell/AppRail.js';
import { MobileTabBar } from '../src/shell/MobileTabBar.js';
import { MobileTopBar } from '../src/shell/MobileTopBar.js';

export default {
  title: 'YarvelleUI/AllFamilies',
};

export function PrimitivesShowcase() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Primitives Family</CardTitle>
        <CardDescription>Token-driven buttons, badges, and cards</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2">
          <Button variant="primary">Primary Action</Button>
          <Button variant="secondary">Secondary</Button>
          <Badge variant="success">Active</Badge>
          <Badge variant="warn">Pending</Badge>
          <SegmentedControl
            options={[
              { value: 'day', label: 'Day' },
              { value: 'week', label: 'Week' },
            ]}
          />
        </div>
      </CardContent>
    </Card>
  );
}

export function ChatAndApprovalShowcase() {
  return (
    <div className="flex flex-col gap-3">
      <ChatMarkdown content="Schedule a **recurring reminder** for Monday." />
      <ThinkingIndicator label="Reasoning..." reasoning="Checking calendar availability" />
      <ExecutionPlanCard
        steps={[
          { id: '1', description: 'Check schedule conflicts', status: 'completed' },
          { id: '2', description: 'Prepare reminder draft', status: 'running' },
        ]}
      />
      <ToolTraceCard
        trace={{
          id: 't-1',
          toolName: 'create_reminder',
          status: 'success',
          durationMs: 42,
        }}
      />
      <ApprovalCard id="apr-story-1" level="warn" label="Create recurring Monday reminder" />
    </div>
  );
}

export function CalendarAndRemindersShowcase() {
  return (
    <div className="flex flex-col gap-4">
      <Calendar
        events={[
          { id: 'e1', title: 'Morning Check-in', start: '2026-10-19T09:00:00Z', end: '2026-10-19T09:30:00Z' },
          { id: 'e2', title: 'Overlapping Sync', start: '2026-10-20T14:00:00Z', end: '2026-10-20T15:00:00Z', conflict: true },
        ]}
      />
      <Reminders
        reminders={[
          { id: 'r1', title: 'Daily Review', dueAt: '08:00 AM', rrule: 'FREQ=DAILY', completed: false },
        ]}
      />
      <Routines
        routines={[
          { id: 'rt1', title: 'Morning review', frequency: 'daily', timeOfDay: '8:00 AM', active: true },
        ]}
      />
      <ActivityTimeline
        events={[{ id: 't1', title: 'Record updated', timestamp: '10:00 AM', status: 'info' }]}
      />
    </div>
  );
}

export function NotesProfilesTasksShowcase() {
  return (
    <div className="flex flex-col gap-4">
      <MemberCard
        member={{
          id: 'm1',
          displayName: 'Alex',
          role: 'owner',
          scopes: ['household'],
        }}
      />
      <RoleMatrix
        permissions={[
          { domain: 'household', read: true, write: true, approve: false },
        ]}
      />
      <TeenHandoverBanner memberName="Sam" handoverDate="2026-12-01" />
      <RecordSearch
        searchQuery=""
        onSearchChange={() => {}}
        selectedFilter="all"
        onFilterChange={() => {}}
      />
      <NotesList
        notes={[
          {
            id: 'n1',
            title: 'Weekly Notes',
            content: 'Summary of items',
            createdAt: '2026-10-19',
            updatedAt: '2026-10-19',
          },
        ]}
        onSelectNote={() => {}}
      />
      <TaskList
        tasks={[{ id: 't1', title: 'Verify backup archive', completed: false }]}
      />
      <NotificationCenter
        notifications={[{ id: 'notif1', title: 'Sync completed', read: false, timestamp: 'Just now' }]}
      />
    </div>
  );
}

export function ShellAndSettingsShowcase() {
  return (
    <div className="flex flex-col gap-3">
      <MobileTopBar title="Overview" />
      <AppRail
        items={[
          { id: 'home', label: 'Home' },
          { id: 'chat', label: 'Chat' },
          { id: 'settings', label: 'Settings' },
        ]}
      />
      <MobileTabBar
        items={[
          { id: 'home', label: 'Home' },
          { id: 'chat', label: 'Chat' },
        ]}
      />
    </div>
  );
}
