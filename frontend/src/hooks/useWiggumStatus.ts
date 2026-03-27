import { useEffect, useRef, useState, useCallback } from 'react';
import type { ApiClient } from '../lib/api';

export interface WiggumRun {
  id: string;
  org_id: string;
  project_id: string;
  branch: string;
  github_run_id: number | null;
  status: 'pending' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
  cycles: number;
  experiments: number;
  model: string;
  started_at: string;
  completed_at: string | null;
  best_accuracy: number | null;
  accuracy_history: string | null;
  github_url?: string;
}

const ACTIVE_STATUSES = new Set(['pending', 'queued', 'in_progress']);
const POLL_INTERVAL = 15_000;

export function useWiggumStatus(api: ApiClient, enabled: boolean) {
  const [run, setRun] = useState<WiggumRun | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getWiggumStatus();
      setRun(data.run ?? null);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    }
  }, [api]);

  // Start/stop polling based on run status
  useEffect(() => {
    if (!enabled) return;

    fetchStatus();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchStatus]);

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    const isActive = run && ACTIVE_STATUSES.has(run.status);
    setIsPolling(!!isActive);

    if (isActive) {
      timerRef.current = setInterval(fetchStatus, POLL_INTERVAL);
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [run?.status, fetchStatus]);

  return { run, isPolling, error, refetch: fetchStatus };
}
