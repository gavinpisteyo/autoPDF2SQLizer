import { useState } from 'react';
import { useWiggumStatus } from '../hooks/useWiggumStatus';
import { useAuthContext } from '../lib/auth';
import type { ApiClient } from '../lib/api';
import StatusMessage from './StatusMessage';

interface GtDoc {
  doc_type: string;
  name: string;
  has_truth_json: boolean;
  has_cache: boolean;
}

interface WiggumPanelProps {
  api: ApiClient;
  docs: GtDoc[];
}

const MODELS = [
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4 (faster, cheaper)' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4 (most capable)' },
];

function formatElapsed(startedAt: string): string {
  const diff = Date.now() - new Date(startedAt).getTime();
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    pending: 'bg-white/[0.06] text-mid',
    queued: 'bg-white/[0.06] text-mid',
    in_progress: 'bg-coral/15 text-coral',
    completed: 'bg-sage-bg text-sage',
    failed: 'bg-red-500/15 text-red-400',
    cancelled: 'bg-white/[0.06] text-mid',
  };
  return (
    <span className={`text-[0.6875rem] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-sm ${styles[status] || styles.pending}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

export default function WiggumPanel({ api, docs }: WiggumPanelProps) {
  const { roleAtLeast } = useAuthContext();
  const { run, isPolling, refetch } = useWiggumStatus(api, true);

  const [cycles, setCycles] = useState(5);
  const [experiments, setExperiments] = useState(5);
  const [model, setModel] = useState(MODELS[0].value);
  const [starting, setStarting] = useState(false);
  const [msg, setMsg] = useState<{ text: string; type: 'success' | 'error' | 'loading' | null }>({ text: '', type: null });
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);

  const hasGroundTruth = docs.length > 0;
  const allCached = hasGroundTruth && docs.every(d => d.has_cache);
  const canStart = roleAtLeast('developer') && hasGroundTruth && allCached;
  const isActive = run && ['pending', 'queued', 'in_progress'].includes(run.status);

  const handleStart = async () => {
    setStarting(true);
    setMsg({ text: 'Starting optimization...', type: 'loading' });
    try {
      const result = await api.startWiggum(cycles, experiments, model);
      setMsg({ text: `Started on branch ${result.branch}`, type: 'success' });
      refetch();
    } catch (e: unknown) {
      setMsg({ text: e instanceof Error ? e.message : 'Failed to start', type: 'error' });
    } finally {
      setStarting(false);
    }
  };

  const loadHistory = async () => {
    try {
      const data = await api.getWiggumHistory();
      setHistory(data.runs || []);
    } catch {}
    setShowHistory(prev => !prev);
  };

  // Don't render if user doesn't have at least viewer access
  if (!roleAtLeast('viewer')) return null;

  return (
    <div className="mt-10 pt-10 border-t border-border">
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Optimization Loop
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-6">
        Autonomously improve extraction accuracy by running the Wiggum loop on your ground truth data.
      </p>

      {/* Active run display */}
      {isActive && run && (
        <div className="bg-surface border border-border-strong rounded-lg p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-coral animate-pulse" />
              <span className="text-sm font-medium text-silver">Optimization Running</span>
            </div>
            {statusBadge(run.status)}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[0.8125rem]">
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Branch</div>
              <div className="text-silver font-mono text-xs">{run.branch}</div>
            </div>
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Model</div>
              <div className="text-silver">{run.model.replace('claude-', '').split('-')[0]}</div>
            </div>
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Elapsed</div>
              <div className="text-silver">{formatElapsed(run.started_at)}</div>
            </div>
            {run.best_accuracy !== null && (
              <div>
                <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Best Accuracy</div>
                <div className="text-sage font-semibold">{(run.best_accuracy * 100).toFixed(1)}%</div>
              </div>
            )}
          </div>

          {run.github_url && (
            <a
              href={run.github_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-4 text-[0.8125rem] text-coral hover:underline"
            >
              View on GitHub &rarr;
            </a>
          )}

          {isPolling && (
            <p className="text-[0.6875rem] text-mid mt-3">Auto-refreshing every 15 seconds...</p>
          )}
        </div>
      )}

      {/* Completed run */}
      {run && run.status === 'completed' && !isActive && (
        <div className="bg-surface border border-sage/20 rounded-lg p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-silver">Last Run Complete</span>
            {statusBadge(run.status)}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[0.8125rem]">
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Branch</div>
              <div className="text-silver font-mono text-xs">{run.branch}</div>
            </div>
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Final Accuracy</div>
              <div className="text-sage font-semibold">
                {run.best_accuracy !== null ? `${(run.best_accuracy * 100).toFixed(1)}%` : 'N/A'}
              </div>
            </div>
            <div>
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Completed</div>
              <div className="text-silver">{run.completed_at ? new Date(run.completed_at).toLocaleString() : 'N/A'}</div>
            </div>
            {run.github_url && (
              <div>
                <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-0.5">Changes</div>
                <a href={run.github_url} target="_blank" rel="noopener noreferrer"
                  className="text-coral hover:underline">View branch &rarr;</a>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Failed run */}
      {run && run.status === 'failed' && (
        <div className="bg-surface border border-red-500/20 rounded-lg p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-silver">Last Run Failed</span>
            {statusBadge(run.status)}
          </div>
          <p className="text-[0.8125rem] text-mid">
            The optimization run encountered an error.
            {run.github_url && (
              <> <a href={run.github_url} target="_blank" rel="noopener noreferrer"
                className="text-coral hover:underline">Check GitHub logs &rarr;</a></>
            )}
          </p>
        </div>
      )}

      {/* Start controls (only when no active run) */}
      {!isActive && roleAtLeast('developer') && (
        <div className="bg-surface border border-border-strong rounded-lg p-5 mb-6">
          {!hasGroundTruth && (
            <p className="text-[0.8125rem] text-mid mb-4">
              Upload ground truth documents above to enable optimization.
            </p>
          )}
          {hasGroundTruth && !allCached && (
            <p className="text-[0.8125rem] text-mid mb-4">
              Cache all ground truth documents via Doc Intel before starting.
            </p>
          )}
          {canStart && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5">
                <div>
                  <label className="block text-[0.6875rem] text-mid uppercase tracking-wide mb-1.5">Cycles</label>
                  <input
                    type="number" min={1} max={50} value={cycles}
                    onChange={e => setCycles(Number(e.target.value))}
                    className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-[0.6875rem] text-mid uppercase tracking-wide mb-1.5">Experiments per Cycle</label>
                  <input
                    type="number" min={1} max={20} value={experiments}
                    onChange={e => setExperiments(Number(e.target.value))}
                    className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-[0.6875rem] text-mid uppercase tracking-wide mb-1.5">Model</label>
                  <select
                    value={model}
                    onChange={e => setModel(e.target.value)}
                    className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
                  >
                    {MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleStart}
                  disabled={starting}
                  className="px-6 py-2.5 text-[0.8125rem] font-semibold bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {starting ? 'Starting...' : 'Start Optimization'}
                </button>
                <span className="text-[0.8125rem] text-mid">
                  {docs.length} ground truth doc{docs.length !== 1 ? 's' : ''} ready
                </span>
              </div>
            </>
          )}
          <StatusMessage message={msg.text} type={msg.type} />
        </div>
      )}

      {/* History toggle */}
      <button
        onClick={loadHistory}
        className="text-[0.8125rem] text-mid hover:text-silver transition-colors"
      >
        {showHistory ? 'Hide' : 'Show'} run history
      </button>

      {showHistory && history.length > 0 && (
        <div className="mt-3">
          <table className="w-full text-[0.8125rem]">
            <thead>
              <tr className="text-left text-[0.6875rem] text-mid uppercase tracking-wide border-b border-border">
                <th className="pb-2 pr-4">Date</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Accuracy</th>
                <th className="pb-2 pr-4">Model</th>
                <th className="pb-2">Branch</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h: Record<string, unknown>) => (
                <tr key={h.id as string} className="border-b border-border/50">
                  <td className="py-2 pr-4 text-silver">
                    {new Date(h.started_at as string).toLocaleDateString()}
                  </td>
                  <td className="py-2 pr-4">{statusBadge(h.status as string)}</td>
                  <td className="py-2 pr-4 text-silver">
                    {h.best_accuracy !== null ? `${((h.best_accuracy as number) * 100).toFixed(1)}%` : '-'}
                  </td>
                  <td className="py-2 pr-4 text-mid">
                    {(h.model as string).replace('claude-', '').split('-')[0]}
                  </td>
                  <td className="py-2 font-mono text-xs text-mid">{h.branch as string}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showHistory && history.length === 0 && (
        <p className="mt-3 text-[0.8125rem] text-mid">No optimization runs yet.</p>
      )}
    </div>
  );
}
