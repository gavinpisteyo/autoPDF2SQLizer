import { useOptimizationStatus } from '../hooks/useOptimizationStatus';
import type { ApiClient } from '../lib/api';

interface OptimizationBannerProps {
  api: ApiClient;
  projectId: string;
  onComplete: () => void;
  onGoToChat: () => void;
}

export default function OptimizationBanner({ api, projectId, onComplete, onGoToChat }: OptimizationBannerProps) {
  const { run, displayedAccuracy, isOptimizing, isComplete, error, refetch } = useOptimizationStatus(api, true, projectId);

  const status = run?.status || 'pending';

  // Failed state — show retry
  if (status === 'failed' || error) {
    return (
      <div className="bg-red-500/[0.06] border border-red-500/20 rounded-lg p-5 mb-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
            <div>
              <p className="text-[0.8125rem] font-medium text-red-400">
                Optimization encountered an issue
              </p>
              <p className="text-[0.6875rem] text-mid mt-0.5">
                {error || 'The optimization run failed. Your corrections have been saved — you can retry or continue.'}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={async () => {
                try {
                  await api.startBackgroundOptimization(projectId);
                  refetch();
                } catch {}
              }}
              className="px-4 py-2 text-xs font-medium bg-coral/20 text-coral rounded-md
                         hover:bg-coral/30 transition-colors"
            >
              Retry
            </button>
            <button
              onClick={onComplete}
              className="px-4 py-2 text-xs font-medium bg-transparent border border-border-strong text-mid rounded-md
                         hover:bg-white/[0.04] transition-colors"
            >
              Continue Anyway
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Optimizing state
  if (isOptimizing) {
    return (
      <div className="bg-coral/[0.06] border border-coral/20 rounded-lg p-5 mb-5">
        <div className="flex items-center gap-3">
          <div className="w-2.5 h-2.5 rounded-full bg-coral animate-pulse" />
          <div>
            <p className="text-[0.8125rem] font-medium text-silver">
              Optimizing extraction...
              {displayedAccuracy > 0 && (
                <span className="text-coral ml-2">{displayedAccuracy.toFixed(1)}% accurate</span>
              )}
            </p>
            <p className="text-[0.6875rem] text-mid mt-0.5">
              This may take a few minutes. You can navigate away safely.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Complete state
  if (isComplete) {
    return (
      <div className="bg-sage-bg border border-sage/20 rounded-lg p-5 mb-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-sage" />
            <div>
              <p className="text-[0.8125rem] font-medium text-sage">
                Corrections saved!
                {displayedAccuracy > 0 && (
                  <span className="ml-2">{displayedAccuracy.toFixed(1)}% accuracy</span>
                )}
              </p>
              <p className="text-[0.6875rem] text-mid mt-0.5">
                Your data is ready. Talk to it in Chat or upload more documents.
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onGoToChat}
              className="px-4 py-2 text-xs font-medium bg-sage/20 text-sage rounded-md
                         hover:bg-sage/30 transition-colors"
            >
              Go to Chat
            </button>
            <button
              onClick={onComplete}
              className="px-4 py-2 text-xs font-medium bg-transparent border border-border-strong text-mid rounded-md
                         hover:bg-white/[0.04] transition-colors"
            >
              Upload Another
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Loading / pending state (before first fetch completes)
  return (
    <div className="bg-coral/[0.04] border border-border-strong rounded-lg p-5 mb-5">
      <div className="flex items-center gap-3">
        <div className="w-2.5 h-2.5 rounded-full bg-coral/50 animate-pulse" />
        <p className="text-[0.8125rem] text-mid">Processing corrections...</p>
      </div>
    </div>
  );
}
