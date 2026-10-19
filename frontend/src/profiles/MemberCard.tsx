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
import { Avatar, AvatarFallback, AvatarImage } from '../primitives/Avatar.js';
import { Badge } from '../primitives/Badge.js';
import { Button } from '../primitives/Button.js';
import type { ProfileMember } from './types.js';

export interface MemberCardProps {
  member: ProfileMember;
  onEdit?: (member: ProfileMember) => void;
  className?: string;
}

const roleBadgeVariant: Record<ProfileMember['role'], 'primary' | 'neutral' | 'info' | 'warn'> = {
  owner: 'primary',
  steward: 'info',
  member: 'neutral',
  viewer: 'warn',
};

export function MemberCard({ member, onEdit, className }: MemberCardProps) {
  return (
    <div
      data-slot="member-card"
      className={cn(
        'yc-MemberCard-root flex items-center justify-between rounded-xl border border-border bg-surface p-4 shadow-1',
        className
      )}
    >
      <div className="flex items-center gap-3">
        <Avatar size="md">
          {member.avatarUrl ? (
            <AvatarImage src={member.avatarUrl} alt={member.displayName} />
          ) : (
            <AvatarFallback>
              {member.displayName.substring(0, 2).toUpperCase()}
            </AvatarFallback>
          )}
        </Avatar>

        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-fg">{member.displayName}</span>
            <Badge variant={roleBadgeVariant[member.role]}>{member.role}</Badge>
          </div>
          {member.relationship && (
            <span className="text-xs text-fg-muted">{member.relationship}</span>
          )}
          {member.scopes && member.scopes.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {member.scopes.map((scope) => (
                <span
                  key={scope}
                  className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-muted"
                >
                  {scope}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {onEdit && (
        <Button size="sm" variant="ghost" onClick={() => onEdit(member)}>
          Edit
        </Button>
      )}
    </div>
  );
}
