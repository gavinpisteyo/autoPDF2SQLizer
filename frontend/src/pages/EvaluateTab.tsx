import { useState } from 'react';
import StatusMessage from '../components/StatusMessage';
import * as api from '../lib/api';

export default function EvaluateTab() {
  const [status, setStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [result, setResult] = useState('');
  const [running, setRunning] = useState(false);

  const handleRun = async () => {
    setRunning(true);
    setResult('');
    setStatus({ msg: 'Running evaluation...', type: 'loading' });

    try {
      const data = await api.runEvaluation();
      setStatus({
        msg: data.returncode === 0 ? 'Evaluation complete' : 'Evaluation finished with errors',
        type: data.returncode === 0 ? 'success' : 'error',
      });
      setResult(data.stdout + (data.stderr ? '\n--- stderr ---\n' + data.stderr : ''));
    } catch (e: unknown) {
      setStatus({ msg: e instanceof Error ? e.message : 'Evaluation failed', type: 'error' });
    }
    setRunning(false);
  };

  return (
    <div>
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Run Evaluation</h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Run extraction on all cached ground truth documents and measure field-level accuracy.
      </p>

      <button
        onClick={handleRun}
        disabled={running}
        className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      >
        Run Evaluation
      </button>

      <StatusMessage message={status.msg} type={status.type} />

      {result && (
        <pre className="mt-5 bg-surface border border-border-strong rounded-md p-4 font-mono text-[0.8125rem] text-silver whitespace-pre-wrap overflow-x-auto max-h-[500px] overflow-y-auto leading-relaxed">
          {result}
        </pre>
      )}
    </div>
  );
}
