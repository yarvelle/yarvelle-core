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
import { Chip } from '../primitives/Chip.js';
import type { ViewerInviteData } from './types.js';

export interface ViewerInviteProps {
  availableScopes?: string[];
  onSendInvite?: (data: ViewerInviteData) => Promise<void> | void;
  className?: string;
}

export function ViewerInvite({
  availableScopes = ['general', 'notes', 'calendar', 'finances', 'records'],
  onSendInvite,
  className,
}: ViewerInviteProps) {
  const [email, setEmail] = React.useState('');
  const [selectedScopes, setSelectedScopes] = React.useState<string[]>(['general']);
  const [expiresInDays, setExpiresInDays] = React.useState(7);
  const [sent, setSent] = React.useState(false);
  const [loading, setLoading] = React.useState(false);

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    setLoading(true);
    try {
      await onSendInvite?.({
        email,
        role: 'viewer',
        scopes: selectedScopes,
        expiresInDays,
      });
      setSent(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      data-slot="viewer-invite"
      className={cn(
        'yc-ViewerInvite-root rounded-xl border border-border bg-surface p-6 shadow-1 text-xs',
        className
      )}
    >
      <h3 className="text-base font-bold text-fg">Invite Viewer</h3>
      <p className="mt-1 text-fg-muted leading-relaxed">
        Grant time-limited, read-only access to selected record scopes.
      </p>

      {sent ? (
        <div className="mt-4 rounded-lg bg-success-bg/30 border border-success-border p-4 text-center">
          <span className="font-semibold text-success-fg">Invitation Sent!</span>
          <p className="mt-1 text-fg-muted">An invitation link has been dispatched to {email}.</p>
          <Button
            size="sm"
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setSent(false);
              setEmail('');
            }}
          >
            Invite Another
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="block font-medium text-fg mb-1">Viewer Email Address</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. viewer@example.com"
              className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
            />
          </div>

          <div>
            <label className="block font-medium text-fg mb-1">Allowed Scopes</label>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {availableScopes.map((scope) => (
                <Chip
                  key={scope}
                  selected={selectedScopes.includes(scope)}
                  onClick={() => toggleScope(scope)}
                >
                  {scope}
                </Chip>
              ))}
            </div>
          </div>

          <div>
            <label className="block font-medium text-fg mb-1">Access Expiration</label>
            <select
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
            >
              <option value={1}>24 hours</option>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </div>

          <Button type="submit" variant="primary" size="sm" loading={loading} className="w-full">
            Send Secure Invitation
          </Button>
        </form>
      )}
    </div>
  );
}
