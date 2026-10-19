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

export interface MessageToolbarProps {
  content: string;
  onRetry?: () => void;
  onFeedback?: (rating: 'positive' | 'negative') => void;
  className?: string;
}

export function MessageToolbar({
  content,
  onRetry,
  onFeedback,
  className,
}: MessageToolbarProps) {
  const [copied, setCopied] = React.useState(false);
  const [rated, setRated] = React.useState<'positive' | 'negative' | null>(null);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore
    }
  };

  const handleRate = (rating: 'positive' | 'negative') => {
    setRated(rating);
    onFeedback?.(rating);
  };

  return (
    <div
      data-slot="message-toolbar"
      className={cn(
        'yc-MessageToolbar-root inline-flex items-center gap-1 rounded-md bg-surface-2 p-0.5 text-xs text-fg-muted border border-border shadow-1',
        className
      )}
    >
      <button
        type="button"
        onClick={handleCopy}
        className="rounded px-1.5 py-0.5 hover:bg-surface hover:text-fg"
        aria-label="Copy message text"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded px-1.5 py-0.5 hover:bg-surface hover:text-fg"
          aria-label="Retry message generation"
        >
          Retry
        </button>
      )}

      {onFeedback && (
        <>
          <button
            type="button"
            onClick={() => handleRate('positive')}
            className={cn(
              'rounded px-1.5 py-0.5 hover:bg-surface hover:text-fg',
              rated === 'positive' && 'text-primary font-bold'
            )}
            aria-label="Helpful"
          >
            👍
          </button>
          <button
            type="button"
            onClick={() => handleRate('negative')}
            className={cn(
              'rounded px-1.5 py-0.5 hover:bg-surface hover:text-fg',
              rated === 'negative' && 'text-danger-fg font-bold'
            )}
            aria-label="Not helpful"
          >
            👎
          </button>
        </>
      )}
    </div>
  );
}
