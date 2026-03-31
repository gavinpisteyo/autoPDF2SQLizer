import { useOptimizationStatus } from '../hooks/useOptimizationStatus';
import type { ApiClient } from '../lib/api';

interface OptimizationBannerProps {
  api: ApiClient;
  projectId: string;
  onComplete: () => void;
  onGoToChat: () => void;
}

export default function OptimizationBanner({ api, projectId, onComplete, onGoToChat }: OptimizationBannerProps) {
  const { displayedAccuracy, isOptimizing, isComplete, error } = useOptimizationStatus(api, true, projectId);

  // Error state
  if (error) {
    return (
      <div className="sticky top-0 z-40 bg-red-500/10 border border-red-500/20 rounded-lg p-4 mb-5">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-red-400" />
          <p className="text-[0.8125rem] text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  // Optimizing state
  if (isOptimizing) {
    return (
      <div className="sticky top-0 z-40 bg-coral/[0.08] border border-coral/20 rounded-lg p-5 mb-5">
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
      <div className="sticky top-0 z-40 bg-sage-bg border border-sage/20 rounded-lg p-5 mb-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-sage" />
            <div>
              <p className="text-[0.8125rem] font-medium text-sage">
                Extraction optimized!
                {displayedAccuracy > 0 && (
                  <span className="ml-2">{displayedAccuracy.toFixed(1)}% accuracy</span>
                )}
              </p>
              <p className="text-[0.6875rem] text-mid mt-0.5">
                Your data is ready in Chat.
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
              Continue
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
