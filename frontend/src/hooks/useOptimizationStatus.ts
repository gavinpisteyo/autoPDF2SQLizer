import { useEffect, useRef, useState, useCallback } from 'react';
import type { ApiClient } from '../lib/api';

export interface OptimizationRun {
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
const POLL_INTERVAL = 10_000;

export function useOptimizationStatus(api: ApiClient, enabled: boolean) {
  const [run, setRun] = useState<OptimizationRun | null>(null);
  const [displayedAccuracy, setDisplayedAccuracy] = useState<number>(0);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const highWaterRef = useRef<number>(0);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getWiggumStatus();
      const latestRun: OptimizationRun | null = data.run ?? null;
      setRun(latestRun);
      setError(null);

      if (latestRun?.best_accuracy !== null && latestRun?.best_accuracy !== undefined) {
        const pct = latestRun.best_accuracy * 100;
        // Ratcheting: only go up, never down
        if (pct > highWaterRef.current) {
          highWaterRef.current = pct;
          setDisplayedAccuracy(pct);
        }
      }

      const active = latestRun !== null && ACTIVE_STATUSES.has(latestRun.status);
      setIsOptimizing(active);
      setIsComplete(latestRun?.status === 'completed');

      if (latestRun?.status === 'failed') {
        setError('Optimization run failed');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    }
  }, [api]);

  // Initial fetch and cleanup
  useEffect(() => {
    if (!enabled) return;
    fetchStatus();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchStatus]);

  // Start/stop polling based on run status
  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    const isActive = run && ACTIVE_STATUSES.has(run.status);

    if (isActive) {
      timerRef.current = setInterval(fetchStatus, POLL_INTERVAL);
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [run?.status, fetchStatus]);

  return {
    run,
    displayedAccuracy,
    isOptimizing,
    isComplete,
    error,
    refetch: fetchStatus,
  };
}
