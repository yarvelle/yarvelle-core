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

import React, { useEffect, useState } from 'react';
import type { ComponentType } from 'react';
import type { SlotContribution, SlotProps } from './types.js';

export interface SlotRendererProps {
  contribution: SlotContribution;
  slotProps: SlotProps;
  fallback?: React.ReactNode;
}

export const SlotRenderer: React.FC<SlotRendererProps> = ({
  contribution,
  slotProps,
  fallback = null,
}) => {
  const [LoadedComp, setLoadedComp] = useState<ComponentType<SlotProps> | null>(() => contribution.component ?? null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (contribution.component) {
      setLoadedComp(() => contribution.component ?? null);
      return;
    }
    if (contribution.load) {
      contribution
        .load()
        .then((mod) => {
          if (!cancelled) {
            setLoadedComp(() => mod.default);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof Error ? err : new Error(String(err)));
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, [contribution]);

  if (error) {
    return (
      <div className="yc-SlotRenderer-error text-danger text-sm p-4" data-slot="error">
        Failed to load slot: {contribution.id}
      </div>
    );
  }

  if (!LoadedComp) {
    return <>{fallback}</>;
  }

  return (
    <div className="yc-SlotRenderer-root" data-slot="root" data-pack={contribution.pack} data-contribution={contribution.id}>
      <LoadedComp {...slotProps} />
    </div>
  );
};
