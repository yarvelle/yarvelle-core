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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from '../primitives/Dialog.js';
import { Button } from '../primitives/Button.js';
import type { ProfileMember, ProfileRole } from './types.js';

export interface ProfileEditModalProps {
  member?: ProfileMember | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (updated: ProfileMember) => void;
}

export function ProfileEditModal({
  member,
  open,
  onOpenChange,
  onSave,
}: ProfileEditModalProps) {
  const [displayName, setDisplayName] = React.useState(member?.displayName || '');
  const [relationship, setRelationship] = React.useState(member?.relationship || '');
  const [role, setRole] = React.useState<ProfileRole>(member?.role || 'member');

  React.useEffect(() => {
    if (member) {
      setDisplayName(member.displayName);
      setRelationship(member.relationship || '');
      setRole(member.role);
    }
  }, [member]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!member) return;
    onSave({
      ...member,
      displayName,
      relationship,
      role,
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="yc-ProfileEditModal-content max-w-md">
        <form onSubmit={handleSubmit} data-slot="profile-edit-modal">
          <DialogHeader>
            <DialogTitle>Edit Profile</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-4 text-xs">
            <div>
              <label className="block font-medium text-fg mb-1">Display Name</label>
              <input
                type="text"
                required
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
              />
            </div>

            <div>
              <label className="block font-medium text-fg mb-1">Relationship</label>
              <input
                type="text"
                value={relationship}
                onChange={(e) => setRelationship(e.target.value)}
                placeholder="e.g. Self, Spouse, Child, Ward"
                className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
              />
            </div>

            <div>
              <label className="block font-medium text-fg mb-1">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as ProfileRole)}
                className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
              >
                <option value="owner">Owner</option>
                <option value="steward">Steward</option>
                <option value="member">Member</option>
                <option value="viewer">Viewer</option>
              </select>
            </div>
          </div>

          <DialogFooter className="gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" variant="primary" size="sm">
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
