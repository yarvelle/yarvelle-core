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
import * as React from 'react';
import { renderToString } from 'react-dom/server';

// Primitives
import { Button } from '../src/primitives/Button.js';
import { Card, CardHeader, CardTitle, CardContent } from '../src/primitives/Card.js';
import { Badge } from '../src/primitives/Badge.js';
import { Avatar, AvatarFallback } from '../src/primitives/Avatar.js';
import { Chip } from '../src/primitives/Chip.js';
import { EmptyState } from '../src/primitives/EmptyState.js';
import { Skeleton } from '../src/primitives/Skeleton.js';
import { InlineError } from '../src/primitives/InlineError.js';
import { SegmentedControl } from '../src/primitives/Segmented.js';

// Chat
import { ApprovalCard } from '../src/chat/ApprovalCard.js';
import { ToolTraceCard } from '../src/chat/ToolTraceCard.js';
import { ExecutionPlanCard } from '../src/chat/ExecutionPlanCard.js';
import { ThinkingIndicator } from '../src/chat/ThinkingIndicator.js';
import { CodeBlock } from '../src/chat/CodeBlock.js';
import { ChatMarkdown } from '../src/chat/ChatMarkdown.js';

// Notes
import { RecordSearch } from '../src/notes/RecordSearch.js';
import { NotesList } from '../src/notes/NotesList.js';
import { NoteView } from '../src/notes/NoteView.js';

// Calendar
import { Calendar } from '../src/calendar/Calendar.js';
import { Reminders } from '../src/calendar/Reminders.js';
import { Routines } from '../src/calendar/Routines.js';
import { ActivityTimeline } from '../src/calendar/ActivityTimeline.js';

// Profiles
import { MemberCard } from '../src/profiles/MemberCard.js';
import { RoleMatrix } from '../src/profiles/RoleMatrix.js';
import { TeenHandoverBanner } from '../src/profiles/TeenHandoverBanner.js';

// Tasks
import { TaskItem } from '../src/tasks/TaskItem.js';
import { TaskList } from '../src/tasks/TaskList.js';

// Notifications
import { NotificationCenter } from '../src/notifications/NotificationCenter.js';

// Shell
import { AppRail } from '../src/shell/AppRail.js';
import { MobileTabBar } from '../src/shell/MobileTabBar.js';
import { MobileTopBar } from '../src/shell/MobileTopBar.js';

describe('Domain-Neutral Component Module Rendering & Data-Slots', () => {
  it('renders primitives with stable yc-* classes and data-slot attributes', () => {
    const btnHtml = renderToString(<Button variant="primary">Click Me</Button>);
    expect(btnHtml).toContain('yc-Button-root');
    expect(btnHtml).toContain('data-slot="button"');

    const cardHtml = renderToString(
      <Card>
        <CardHeader>
          <CardTitle>Title</CardTitle>
        </CardHeader>
        <CardContent>Content</CardContent>
      </Card>
    );
    expect(cardHtml).toContain('yc-Card-root');
    expect(cardHtml).toContain('yc-Card-title');

    const badgeHtml = renderToString(<Badge variant="success">Active</Badge>);
    expect(badgeHtml).toContain('yc-Badge-root');
    expect(badgeHtml).toContain('data-slot="badge"');

    const avatarHtml = renderToString(
      <Avatar>
        <AvatarFallback>BJ</AvatarFallback>
      </Avatar>
    );
    expect(avatarHtml).toContain('yc-Avatar-root');

    const chipHtml = renderToString(<Chip selected>Filter</Chip>);
    expect(chipHtml).toContain('yc-Chip-root');
    expect(chipHtml).toContain('data-slot="chip"');

    const emptyHtml = renderToString(<EmptyState title="Nothing here" />);
    expect(emptyHtml).toContain('yc-EmptyState-root');
    expect(emptyHtml).toContain('data-slot="empty-state"');

    const skeletonHtml = renderToString(<Skeleton className="h-4 w-20" />);
    expect(skeletonHtml).toContain('yc-Skeleton-root');
    expect(skeletonHtml).toContain('data-slot="skeleton"');

    const errorHtml = renderToString(<InlineError message="Something failed" />);
    expect(errorHtml).toContain('yc-InlineError-root');
    expect(errorHtml).toContain('data-slot="inline-error"');

    const segHtml = renderToString(
      <SegmentedControl
        options={[
          { value: 'a', label: 'Option A' },
          { value: 'b', label: 'Option B' },
        ]}
      />
    );
    expect(segHtml).toContain('yc-Segmented-root');
    expect(segHtml).toContain('data-slot="segmented-control"');
  });

  it('renders chat components with stable yc-Chat-* / yc-* classes', () => {
    const approvalHtml = renderToString(
      <ApprovalCard id="app-1" level="warn" label="Run External Tool" />
    );
    expect(approvalHtml).toContain('yc-ApprovalCard-root');
    expect(approvalHtml).toContain('data-slot="approval-card"');
    expect(approvalHtml).toContain('data-risk-level="warn"');

    const traceHtml = renderToString(
      <ToolTraceCard
        trace={{
          id: 't-1',
          toolName: 'read_record',
          status: 'success',
          durationMs: 42,
        }}
      />
    );
    expect(traceHtml).toContain('yc-ToolTraceCard-root');
    expect(traceHtml).toContain('data-slot="tool-trace-card"');

    const planHtml = renderToString(
      <ExecutionPlanCard
        steps={[
          { id: '1', description: 'Analyze input', status: 'completed' },
          { id: '2', description: 'Synthesize answer', status: 'running' },
        ]}
      />
    );
    expect(planHtml).toContain('yc-ExecutionPlanCard-root');
    expect(planHtml).toContain('data-slot="execution-plan-card"');

    const thinkingHtml = renderToString(
      <ThinkingIndicator label="Reasoning..." reasoning="Step 1 analysis" />
    );
    expect(thinkingHtml).toContain('yc-ThinkingIndicator-root');
    expect(thinkingHtml).toContain('data-slot="thinking-indicator"');

    const codeHtml = renderToString(<CodeBlock code="const a = 1;" language="typescript" />);
    expect(codeHtml).toContain('yc-CodeBlock-root');
    expect(codeHtml).toContain('data-slot="code-block"');

    const markdownHtml = renderToString(
      <ChatMarkdown content="Hello **world**\n```js\nconsole.log(1);\n```" />
    );
    expect(markdownHtml).toContain('yc-ChatMarkdown-root');
    expect(markdownHtml).toContain('data-slot="chat-markdown"');
  });

  it('renders notes components', () => {
    const searchHtml = renderToString(
      <RecordSearch
        searchQuery=""
        onSearchChange={() => {}}
        selectedFilter="all"
        onFilterChange={() => {}}
      />
    );
    expect(searchHtml).toContain('yc-RecordSearch-root');
    expect(searchHtml).toContain('data-slot="record-search"');

    const listHtml = renderToString(
      <NotesList
        notes={[
          {
            id: 'n1',
            title: 'Note 1',
            content: 'Content 1',
            createdAt: '2026-10-19',
            updatedAt: '2026-10-19',
          },
        ]}
        onSelectNote={() => {}}
      />
    );
    expect(listHtml).toContain('yc-NotesList-root');
    expect(listHtml).toContain('data-slot="notes-list"');

    const viewHtml = renderToString(
      <NoteView
        note={{
          id: 'n1',
          title: 'Note 1',
          content: 'Details',
          createdAt: '2026-10-19',
          updatedAt: '2026-10-19',
        }}
      />
    );
    expect(viewHtml).toContain('yc-NoteView-root');
    expect(viewHtml).toContain('data-slot="note-view"');
  });

  it('renders calendar components', () => {
    const calHtml = renderToString(
      <Calendar events={[{ id: 'e1', title: 'Review', start: new Date(), end: new Date() }]} />
    );
    expect(calHtml).toContain('yc-Calendar-root');
    expect(calHtml).toContain('data-slot="calendar"');

    const remHtml = renderToString(
      <Reminders
        reminders={[{ id: 'r1', title: 'Follow up', dueAt: '2:00 PM', completed: false }]}
      />
    );
    expect(remHtml).toContain('yc-Reminders-root');
    expect(remHtml).toContain('data-slot="reminders"');

    const routHtml = renderToString(
      <Routines
        routines={[
          { id: 'rt1', title: 'Morning review', frequency: 'daily', timeOfDay: '8:00 AM', active: true },
        ]}
      />
    );
    expect(routHtml).toContain('yc-Routines-root');
    expect(routHtml).toContain('data-slot="routines"');

    const timelineHtml = renderToString(
      <ActivityTimeline
        events={[{ id: 't1', title: 'File added', timestamp: '10:00 AM', status: 'info' }]}
      />
    );
    expect(timelineHtml).toContain('yc-ActivityTimeline-root');
    expect(timelineHtml).toContain('data-slot="activity-timeline"');
  });

  it('renders profiles components', () => {
    const memberHtml = renderToString(
      <MemberCard
        member={{
          id: 'm1',
          displayName: 'Primary Member',
          role: 'owner',
          scopes: ['general'],
        }}
      />
    );
    expect(memberHtml).toContain('yc-MemberCard-root');
    expect(memberHtml).toContain('data-slot="member-card"');

    const matrixHtml = renderToString(
      <RoleMatrix
        permissions={[
          { domain: 'general', read: true, write: true, approve: true },
          { domain: 'finance', read: true, write: false, approve: false },
        ]}
      />
    );
    expect(matrixHtml).toContain('yc-RoleMatrix-root');
    expect(matrixHtml).toContain('data-slot="role-matrix"');

    const bannerHtml = renderToString(
      <TeenHandoverBanner memberName="Alex" handoverDate="2026-12-01" />
    );
    expect(bannerHtml).toContain('yc-TeenHandoverBanner-root');
    expect(bannerHtml).toContain('data-slot="teen-handover-banner"');
  });

  it('renders tasks components', () => {
    const itemHtml = renderToString(
      <TaskItem
        task={{
          id: 'tk1',
          title: 'Review proposal',
          completed: false,
          priority: 'high',
        }}
      />
    );
    expect(itemHtml).toContain('yc-TaskItem-root');
    expect(itemHtml).toContain('data-slot="task-item"');

    const listHtml = renderToString(
      <TaskList
        tasks={[
          { id: 'tk1', title: 'Task 1', completed: false },
          { id: 'tk2', title: 'Task 2', completed: true },
        ]}
      />
    );
    expect(listHtml).toContain('yc-TaskList-root');
    expect(listHtml).toContain('data-slot="task-list"');
  });

  it('renders notifications components', () => {
    const notifHtml = renderToString(
      <NotificationCenter
        notifications={[
          { id: 'nt1', title: 'Welcome', read: false, timestamp: '1m ago' },
        ]}
      />
    );
    expect(notifHtml).toContain('yc-NotificationCenter-root');
    expect(notifHtml).toContain('data-slot="notification-center"');
  });

  it('renders shell components', () => {
    const railHtml = renderToString(
      <AppRail
        items={[
          { id: 'home', label: 'Home' },
          { id: 'notes', label: 'Notes' },
        ]}
      />
    );
    expect(railHtml).toContain('yc-AppRail-root');
    expect(railHtml).toContain('data-slot="app-rail"');

    const topHtml = renderToString(<MobileTopBar title="Overview" />);
    expect(topHtml).toContain('yc-MobileTopBar-root');
    expect(topHtml).toContain('data-slot="mobile-top-bar"');

    const tabHtml = renderToString(
      <MobileTabBar
        items={[
          { id: 'home', label: 'Home' },
          { id: 'chat', label: 'Chat' },
        ]}
      />
    );
    expect(tabHtml).toContain('yc-MobileTabBar-root');
    expect(tabHtml).toContain('data-slot="mobile-tab-bar"');
  });
});
