import { useState } from 'react';
import * as api from '../lib/api';

interface DocResultCardProps {
  filename: string;
  extracted: Record<string, unknown> | null;
  sourceFile: string;
  docType: string;
  error?: string;
  dbConfig: { dialect: string; tableName: string; schemaName: string; connStr: string; includeDdl: boolean };
  onGroundTruthSaved?: () => void;
}

export default function DocResultCard({
  filename, extracted, sourceFile, docType, error, dbConfig, onGroundTruthSaved,
}: DocResultCardProps) {
  const [open, setOpen] = useState(!!extracted || !!error);
  const [json, setJson] = useState(extracted ? JSON.stringify(extracted, null, 2) : error || '');
  const [msg, setMsg] = useState('');
  const [msgColor, setMsgColor] = useState('text-mid');
  const [sql, setSql] = useState('');
  const [showSql, setShowSql] = useState(false);
  const [sqlMsg, setSqlMsg] = useState('');
  const [sqlMsgColor, setSqlMsgColor] = useState('text-mid');

  const setFeedback = (text: string, color: string) => { setMsg(text); setMsgColor(color); };
  const setSqlFeedback = (text: string, color: string) => { setSqlMsg(text); setSqlMsgColor(color); };

  const handleSaveGt = async () => {
    try { JSON.parse(json); } catch { return setFeedback('Invalid JSON', 'text-rose'); }
    try {
      const data = await api.saveAsGroundTruth(sourceFile, docType, json);
      setFeedback(`Saved: ${data.doc_type}/${data.name}`, 'text-sage');
      onGroundTruthSaved?.();
    } catch (e: unknown) {
      setFeedback(e instanceof Error ? e.message : 'Save failed', 'text-rose');
    }
  };

  const handleGenSql = async () => {
    try {
      const data = await api.generateSql(
        json, dbConfig.tableName || docType, dbConfig.dialect, dbConfig.schemaName, dbConfig.includeDdl,
      );
      setSql(data.sql);
      setShowSql(true);
    } catch (e: unknown) {
      setSqlFeedback(e instanceof Error ? e.message : 'Failed', 'text-rose');
      setShowSql(true);
    }
  };

  const handleExecSql = async () => {
    if (!dbConfig.connStr) return setSqlFeedback('Set connection string in Database tab', 'text-amber');
    setSqlFeedback('Uploading...', 'text-silver');
    try {
      const data = await api.executeSql(sql, dbConfig.connStr);
      const color = data.succeeded === data.total ? 'text-sage' : 'text-amber';
      setSqlFeedback(`${data.succeeded}/${data.total} statements succeeded`, color);
    } catch (e: unknown) {
      setSqlFeedback(e instanceof Error ? e.message : 'Failed', 'text-rose');
    }
  };

  const badge = error
    ? <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-rose-bg text-rose">error</span>
    : extracted
      ? <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">done</span>
      : <span className="text-[0.8125rem] text-mid font-light">extracting...</span>;

  return (
    <div className="border border-border rounded-lg mb-3 overflow-hidden hover:border-border-strong transition-colors">
      <div
        onClick={() => setOpen(!open)}
        className="flex justify-between items-center px-5 py-4 cursor-pointer hover:bg-white/[0.015] transition-colors"
      >
        <h3 className="text-sm font-medium text-silver flex items-center gap-2">
          {filename} {badge}
        </h3>
        <span className={`text-mid text-xs transition-transform duration-200 ${open ? 'rotate-90' : ''}`}>
          &#9654;
        </span>
      </div>

      {open && (
        <div className="px-5 pb-5">
          <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
            Extracted JSON
          </label>
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            className="w-full min-h-[200px] font-mono text-[0.8125rem] leading-relaxed bg-surface border border-border-strong rounded-md text-silver p-3 mb-3 resize-y outline-none focus:border-coral transition-colors"
          />

          <div className="flex gap-2 items-center flex-wrap mb-3">
            <button onClick={handleSaveGt} className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all">
              Save as Ground Truth
            </button>
            <button onClick={handleGenSql} className="px-5 py-2 text-[0.8125rem] font-medium bg-transparent border border-border-strong text-silver rounded-md hover:bg-white/[0.04] hover:border-white/15 active:translate-y-px transition-all">
              Convert to SQL
            </button>
            {msg && <span className={`text-[0.8125rem] ${msgColor}`}>{msg}</span>}
          </div>

          {showSql && (
            <div className="mt-4">
              <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
                Generated SQL
              </label>
              <textarea
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                className="w-full min-h-[150px] font-mono text-[0.8125rem] leading-relaxed bg-surface border border-border-strong rounded-md text-silver p-3 mb-3 resize-y outline-none focus:border-coral transition-colors"
              />
              <div className="flex gap-2 items-center">
                <button onClick={handleExecSql} className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all">
                  Upload to Database
                </button>
                {sqlMsg && <span className={`text-[0.8125rem] ${sqlMsgColor}`}>{sqlMsg}</span>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
