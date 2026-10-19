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
import { Popover, PopoverTrigger, PopoverContent } from '../primitives/Popover.js';
import { Badge } from '../primitives/Badge.js';
import { Button } from '../primitives/Button.js';
import type { NotificationMessage, NotificationLevel } from './types.js';

export interface NotificationCenterProps {
  notifications: NotificationMessage[];
  onMarkAllRead?: () => void;
  onDismiss?: (id: string) => void;
  onSelectNotification?: (notification: NotificationMessage) => void;
  className?: string;
}

const levelBadgeVariant: Record<NotificationLevel, 'info' | 'warn' | 'danger' | 'success'> = {
  info: 'info',
  warn: 'warn',
  danger: 'danger',
  success: 'success',
};

export function NotificationCenter({
  notifications,
  onMarkAllRead,
  onDismiss,
  onSelectNotification,
  className,
}: NotificationCenterProps) {
  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <div
      data-slot="notification-center"
      className={cn('yc-NotificationCenter-root inline-block', className)}
    >
      <Popover>
        <PopoverTrigger className="relative flex items-center justify-center p-2 rounded-lg border border-border bg-surface hover:bg-surface-2 transition-colors">
          <span className="text-base" role="img" aria-label="Notifications">
            🔔
          </span>
          {unreadCount > 0 && (
            <span className="absolute -top-1 -end-1 flex h-4 w-4 items-center justify-center rounded-full bg-danger-fg text-[10px] font-bold text-white">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </PopoverTrigger>

        <PopoverContent align="end" className="w-80 p-0 shadow-3">
          <div className="flex items-center justify-between border-b border-border p-3">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-fg">Notifications</span>
              {unreadCount > 0 && <Badge variant="primary">{unreadCount} new</Badge>}
            </div>
            {unreadCount > 0 && onMarkAllRead && (
              <button
                type="button"
                onClick={onMarkAllRead}
                className="text-xs text-primary hover:underline font-medium"
              >
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-border">
            {notifications.length === 0 ? (
              <div className="p-6 text-center text-xs text-fg-muted">
                No notifications right now.
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  onClick={() => onSelectNotification?.(n)}
                  data-slot="notification-item"
                  data-read={n.read ? 'true' : undefined}
                  className={cn(
                    'flex items-start justify-between p-3 transition-colors text-start cursor-pointer',
                    n.read ? 'bg-surface opacity-75' : 'bg-surface-2/60'
                  )}
                >
                  <div className="flex flex-col gap-0.5 flex-1 pe-2">
                    <div className="flex items-center gap-1.5">
                      {n.level && (
                        <Badge variant={levelBadgeVariant[n.level]} className="text-[9px] px-1 py-0">
                          {n.level}
                        </Badge>
                      )}
                      <span className="font-medium text-xs text-fg">{n.title}</span>
                    </div>
                    {n.description && (
                      <p className="text-[11px] text-fg-muted line-clamp-2">{n.description}</p>
                    )}
                    <span className="text-[10px] text-fg-muted mt-1">{n.timestamp}</span>
                  </div>

                  {onDismiss && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDismiss(n.id);
                      }}
                      className="text-fg-muted hover:text-fg text-xs p-1"
                      aria-label="Dismiss notification"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
