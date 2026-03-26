import { useEffect, useState } from 'react';
import DropZone from '../components/DropZone';
import StatusMessage from '../components/StatusMessage';
import * as api from '../lib/api';

interface GtDoc {
  doc_type: string;
  name: string;
  has_truth_json: boolean;
  has_cache: boolean;
}

interface GroundTruthTabProps {
  schemas: string[];
  refreshKey: number;
}

function stem(filename: string) {
  return filename.replace(/\.[^.]+$/, '');
}

export default function GroundTruthTab({ schemas, refreshKey }: GroundTruthTabProps) {
  const [docType, setDocType] = useState(schemas[0] || '');
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [docs, setDocs] = useState<GtDoc[]>([]);
  const [cacheStatus, setCacheStatus] = useState('');

  const loadDocs = async () => {
    try {
      const data = await api.listGroundTruth();
      setDocs(data);
    } catch {}
  };

  useEffect(() => { loadDocs(); }, [refreshKey]);

  const handleFiles = (newFiles: File[]) => {
    setFiles(prev => [...prev, ...newFiles]);
  };

  const getPairs = () => {
    const pdfs: Record<string, File> = {};
    const jsons: Record<string, File> = {};
    for (const f of files) {
      const s = stem(f.name);
      if (f.name.toLowerCase().endsWith('.pdf')) pdfs[s] = f;
      else if (f.name.toLowerCase().endsWith('.json')) jsons[s] = f;
    }
    const paired: { stem: string; pdf: File; json: File }[] = [];
    const unpaired: { stem: string; type: string }[] = [];
    const allStems = new Set([...Object.keys(pdfs), ...Object.keys(jsons)]);
    for (const s of allStems) {
      if (pdfs[s] && jsons[s]) paired.push({ stem: s, pdf: pdfs[s], json: jsons[s] });
      else if (pdfs[s]) unpaired.push({ stem: s, type: 'pdf (no JSON)' });
      else unpaired.push({ stem: s, type: 'json (no PDF)' });
    }
    return { paired, unpaired };
  };

  const { paired, unpaired } = getPairs();

  const handleUpload = async () => {
    if (!paired.length) return;
    setStatus({ msg: `Uploading ${paired.length} pair(s)...`, type: 'loading' });
    let ok = 0;
    for (const p of paired) {
      try {
        await api.uploadGroundTruth(p.pdf, p.json, docType);
        ok++;
      } catch {}
    }
    setStatus({
      msg: `Uploaded ${ok}/${paired.length} ground truth pairs`,
      type: ok === paired.length ? 'success' : 'error',
    });
    setFiles([]);
    loadDocs();
  };

  const handleCache = async () => {
    setCacheStatus('Running Doc Intel on uncached docs...');
    try {
      const data = await api.cacheGroundTruth();
      const newlyCached = data.filter((d: { status: string }) => d.status === 'cached').length;
      setCacheStatus(`Done. ${newlyCached} newly cached, ${data.length - newlyCached} already cached.`);
      loadDocs();
    } catch (e: unknown) {
      setCacheStatus(`Error: ${e instanceof Error ? e.message : 'unknown'}`);
    }
  };

  return (
    <div>
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Upload Ground Truth</h2>
        <p className="text-[0.8125rem] text-mid font-light mb-5">
          Drop PDFs and their matching JSON files. Auto-paired by filename:&nbsp;
          <code className="font-mono text-xs text-silver bg-white/[0.04] px-1.5 py-0.5 rounded-sm">invoice_001.pdf</code>
          &nbsp;pairs with&nbsp;
          <code className="font-mono text-xs text-silver bg-white/[0.04] px-1.5 py-0.5 rounded-sm">invoice_001.json</code>
        </p>

        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Document Type</label>
        <select
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
          className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-5 outline-none focus:border-coral transition-colors"
        >
          {schemas.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>

        <DropZone accept=".pdf,.json" multiple onFiles={handleFiles}>
          <p className="text-[0.8125rem] font-light">Drop PDFs + JSON files here</p>
        </DropZone>

        {(paired.length > 0 || unpaired.length > 0) && (
          <div className="mb-5">
            {paired.map(p => (
              <div key={p.stem} className="flex justify-between items-center py-1.5 border-b border-border text-[0.8125rem]">
                <span>{p.stem}</span>
                <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">paired</span>
              </div>
            ))}
            {unpaired.map(u => (
              <div key={u.stem} className="flex justify-between items-center py-1.5 border-b border-border text-[0.8125rem]">
                <span>{u.stem}</span>
                <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-white/[0.04] text-mid">{u.type}</span>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={paired.length === 0}
          className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Upload All Pairs
        </button>
        <StatusMessage message={status.msg} type={status.type} />
      </div>

      <div className="h-px bg-border my-10" />

      <div>
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Ground Truth Documents</h2>
        {docs.length === 0 ? (
          <p className="text-[0.8125rem] text-mid">No ground truth documents yet.</p>
        ) : (
          <ul className="list-none">
            {docs.map(d => (
              <li key={`${d.doc_type}-${d.name}`} className="flex justify-between items-center py-2.5 border-b border-border text-[0.8125rem]">
                <span>{d.doc_type}/{d.name}</span>
                <span className="flex gap-1.5">
                  {d.has_truth_json && <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">truth</span>}
                  {d.has_cache
                    ? <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">cached</span>
                    : <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-white/[0.04] text-mid">uncached</span>
                  }
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-5 flex items-center gap-3">
          <button onClick={handleCache} className="px-5 py-2 text-[0.8125rem] font-medium bg-transparent border border-border-strong text-silver rounded-md hover:bg-white/[0.04] hover:border-white/15 active:translate-y-px transition-all">
            Cache All via Doc Intel
          </button>
          {cacheStatus && <span className="text-[0.8125rem] text-mid">{cacheStatus}</span>}
        </div>
      </div>
    </div>
  );
}
