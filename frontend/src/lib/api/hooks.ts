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

import { useCallback, useEffect, useState } from 'react';
import { defaultApiClient } from './client.js';
import type { UiContext, UiPreference, UiPreferenceUpdate } from './types.js';

export function useUiContext(profileId?: string) {
  const [data, setData] = useState<UiContext | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await defaultApiClient.getUiContext(profileId);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}

export function useUiPrefs(profileId: string) {
  const [data, setData] = useState<UiPreference | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    if (!profileId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await defaultApiClient.getUiPrefs(profileId);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const updatePrefs = useCallback(
    async (prefs: UiPreferenceUpdate) => {
      const updated = await defaultApiClient.updateUiPrefs(profileId, prefs);
      setData(updated);
      return updated;
    },
    [profileId]
  );

  return { data, loading, error, refetch, updatePrefs };
}
