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
import type { ShareBundleData } from './types.js';

export interface ShareBundleProps {
  availableScopes?: string[];
  onCreateBundle?: (bundle: Omit<ShareBundleData, 'id'>) => Promise<string> | void;
  className?: string;
}

export function ShareBundle({
  availableScopes = ['general', 'notes', 'calendar', 'finances', 'records'],
  onCreateBundle,
  className,
}: ShareBundleProps) {
  const [name, setName] = React.useState('');
  const [selectedScopes, setSelectedScopes] = React.useState<string[]>(['general']);
  const [requiresPasscode, setRequiresPasscode] = React.useState(false);
  const [bundleLink, setBundleLink] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;
    setLoading(true);
    try {
      const link = await onCreateBundle?.({
        name,
        scopes: selectedScopes,
        requiresPasscode,
      });
      setBundleLink(typeof link === 'string' ? link : 'https://yarvelle.local/bundles/b7a9c3');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      data-slot="share-bundle"
      className={cn(
        'yc-ShareBundle-root rounded-xl border border-border bg-surface p-6 shadow-1 text-xs',
        className
      )}
    >
      <h3 className="text-base font-bold text-fg">Create Share Bundle</h3>
      <p className="mt-1 text-fg-muted leading-relaxed">
        Package records into an encrypted export bundle.
      </p>

      {bundleLink ? (
        <div className="mt-4 rounded-lg bg-surface-2 border border-border p-4 text-center">
          <span className="font-semibold text-fg">Bundle Created!</span>
          <p className="mt-1 text-fg-muted">Shareable bundle link:</p>
          <div className="mt-2 rounded bg-surface p-2 font-mono text-xs text-primary border border-border">
            {bundleLink}
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="mt-3"
            onClick={() => {
              setBundleLink(null);
              setName('');
            }}
          >
            Create Another
          </Button>
        </div>
      ) : (
        <form onSubmit={handleCreate} className="mt-4 space-y-4">
          <div>
            <label className="block font-medium text-fg mb-1">Bundle Name</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Annual Record Dossier"
              className="w-full rounded-md border border-border bg-surface-2 p-2 text-sm text-fg focus:border-primary focus:outline-none"
            />
          </div>

          <div>
            <label className="block font-medium text-fg mb-1">Included Scopes</label>
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

          <div className="flex items-center gap-2">
            <input
              id="passcode-opt"
              type="checkbox"
              checked={requiresPasscode}
              onChange={(e) => setRequiresPasscode(e.target.checked)}
              className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
            />
            <label htmlFor="passcode-opt" className="font-medium text-fg cursor-pointer">
              Protect bundle with passkey / PIN
            </label>
          </div>

          <Button type="submit" variant="primary" size="sm" loading={loading} className="w-full">
            Generate Secure Bundle
          </Button>
        </form>
      )}
    </div>
  );
}
