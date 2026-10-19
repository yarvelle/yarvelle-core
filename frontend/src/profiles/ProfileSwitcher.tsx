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
import { Menu, MenuTrigger, MenuContent, MenuItem } from '../primitives/Menu.js';
import type { ProfileMember } from './types.js';

export interface ProfileSwitcherProps {
  members: ProfileMember[];
  activeMemberId: string;
  onSelectMember: (memberId: string) => void;
  className?: string;
}

export function ProfileSwitcher({
  members,
  activeMemberId,
  onSelectMember,
  className,
}: ProfileSwitcherProps) {
  const activeMember = members.find((m) => m.id === activeMemberId) || members[0];

  return (
    <div
      data-slot="profile-switcher"
      className={cn('yc-ProfileSwitcher-root inline-block', className)}
    >
      <Menu>
        <MenuTrigger className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 shadow-1 hover:bg-surface-2 transition-colors">
          <Avatar size="sm">
            {activeMember?.avatarUrl ? (
              <AvatarImage src={activeMember.avatarUrl} alt={activeMember.displayName} />
            ) : (
              <AvatarFallback>
                {activeMember ? activeMember.displayName.substring(0, 2).toUpperCase() : 'ME'}
              </AvatarFallback>
            )}
          </Avatar>
          <div className="flex flex-col text-start">
            <span className="text-xs font-semibold text-fg">
              {activeMember ? activeMember.displayName : 'Select Profile'}
            </span>
            {activeMember?.relationship && (
              <span className="text-[10px] text-fg-muted">{activeMember.relationship}</span>
            )}
          </div>
          <span className="ms-1 text-xs text-fg-muted">▾</span>
        </MenuTrigger>

        <MenuContent align="start">
          {members.map((member) => (
            <MenuItem
              key={member.id}
              onClick={() => onSelectMember(member.id)}
              className={cn(
                'flex items-center gap-2.5 py-2',
                member.id === activeMemberId && 'bg-surface-2 font-semibold'
              )}
            >
              <Avatar size="sm">
                {member.avatarUrl ? (
                  <AvatarImage src={member.avatarUrl} alt={member.displayName} />
                ) : (
                  <AvatarFallback>
                    {member.displayName.substring(0, 2).toUpperCase()}
                  </AvatarFallback>
                )}
              </Avatar>
              <div className="flex flex-col text-start">
                <span className="text-xs text-fg">{member.displayName}</span>
                <span className="text-[10px] text-fg-muted">
                  {member.relationship || member.role}
                </span>
              </div>
            </MenuItem>
          ))}
        </MenuContent>
      </Menu>
    </div>
  );
}
