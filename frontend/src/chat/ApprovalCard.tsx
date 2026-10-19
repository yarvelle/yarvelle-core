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
import type { RiskLevel, ApprovalRequest } from './types.js';

export interface ApprovalCardProps {
  id: string;
  level: RiskLevel;
  label: string;
  details?: Record<string, unknown>;
  onDecide?: (id: string, decision: 'approved' | 'rejected') => Promise<void> | void;
  status?: 'pending' | 'approved' | 'rejected';
  className?: string;
}

const levelBadgeVariant: Record<RiskLevel, 'info' | 'warn' | 'danger'> = {
  info: 'info',
  warn: 'warn',
  danger: 'danger',
};

const levelBorderStyles: Record<RiskLevel, string> = {
  info: 'border-info-border bg-info-bg/30',
  warn: 'border-warn-border bg-warn-bg/30',
  danger: 'border-danger-border bg-danger-bg/30',
};

export function ApprovalCard({
  id,
  level,
  label,
  details,
  onDecide,
  status = 'pending',
  className,
}: ApprovalCardProps) {
  const [loading, setLoading] = React.useState(false);
  const [currentStatus, setCurrentStatus] = React.useState(status);

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    try {
      setLoading(true);
      if (onDecide) {
        await onDecide(id, decision);
      } else {
        // Default API call to Yarvelle Core approvals endpoint
        await fetch(`/api/v1/approvals/${encodeURIComponent(id)}/decide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision }),
        });
      }
      setCurrentStatus(decision);
    } catch (err) {
      console.error('Failed to submit approval decision:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      data-slot="approval-card"
      data-risk-level={level}
      className={cn(
        'yc-ApprovalCard-root rounded-lg border p-4 shadow-1 transition-colors duration-fast',
        levelBorderStyles[level],
        className
      )}
    >
      <div className="flex items-center justify-between gap-2 pb-2">
        <div className="flex items-center gap-2">
          <Badge variant={levelBadgeVariant[level]}>
            {level.toUpperCase()}
          </Badge>
          <span className="yc-ApprovalCard-title text-sm font-semibold text-fg" data-slot="title">
            {label}
          </span>
        </div>
        {currentStatus !== 'pending' && (
          <Badge variant={currentStatus === 'approved' ? 'success' : 'danger'}>
            {currentStatus === 'approved' ? 'Approved' : 'Rejected'}
          </Badge>
        )}
      </div>

      {details && Object.keys(details).length > 0 && (
        <div className="yc-ApprovalCard-details mt-2 rounded bg-surface/80 p-2.5 text-xs text-fg-muted font-mono" data-slot="details">
          <pre className="overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(details, null, 2)}
          </pre>
        </div>
      )}

      {currentStatus === 'pending' && (
        <div className="yc-ApprovalCard-actions mt-3 flex items-center justify-end gap-2" data-slot="actions">
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => handleDecision('rejected')}
          >
            Reject
          </Button>
          <Button
            size="sm"
            variant={level === 'danger' ? 'danger' : 'primary'}
            loading={loading}
            onClick={() => handleDecision('approved')}
          >
            Approve & Continue
          </Button>
        </div>
      )}
    </div>
  );
}
