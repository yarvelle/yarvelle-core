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
import type { ScopePermission } from './types.js';

export interface RoleMatrixProps {
  permissions: ScopePermission[];
  onChange?: (permissions: ScopePermission[]) => void;
  readOnly?: boolean;
  className?: string;
}

export function RoleMatrix({
  permissions,
  onChange,
  readOnly = false,
  className,
}: RoleMatrixProps) {
  const handleToggle = (
    domainIndex: number,
    field: 'read' | 'write' | 'approve',
    val: boolean
  ) => {
    if (readOnly || !onChange) return;
    const next = [...permissions];
    next[domainIndex] = {
      ...next[domainIndex],
      [field]: val,
    };
    onChange(next);
  };

  return (
    <div
      data-slot="role-matrix"
      className={cn(
        'yc-RoleMatrix-root overflow-x-auto rounded-xl border border-border bg-surface text-fg shadow-1',
        className
      )}
    >
      <table className="w-full text-start text-xs">
        <thead className="border-b border-border bg-surface-2 text-fg-muted font-semibold">
          <tr>
            <th className="p-3 text-start">Domain Scope</th>
            <th className="p-3 text-center">Read</th>
            <th className="p-3 text-center">Write</th>
            <th className="p-3 text-center">Approve</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {permissions.map((perm, idx) => (
            <tr key={perm.domain} className="hover:bg-surface-2/50 transition-colors">
              <td className="p-3 font-medium text-fg capitalize">{perm.domain}</td>
              <td className="p-3 text-center">
                <input
                  type="checkbox"
                  checked={perm.read}
                  disabled={readOnly}
                  onChange={(e) => handleToggle(idx, 'read', e.target.checked)}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50"
                  aria-label={`Read permission for ${perm.domain}`}
                />
              </td>
              <td className="p-3 text-center">
                <input
                  type="checkbox"
                  checked={perm.write}
                  disabled={readOnly}
                  onChange={(e) => handleToggle(idx, 'write', e.target.checked)}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50"
                  aria-label={`Write permission for ${perm.domain}`}
                />
              </td>
              <td className="p-3 text-center">
                <input
                  type="checkbox"
                  checked={perm.approve}
                  disabled={readOnly}
                  onChange={(e) => handleToggle(idx, 'approve', e.target.checked)}
                  className="h-4 w-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50"
                  aria-label={`Approve permission for ${perm.domain}`}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
