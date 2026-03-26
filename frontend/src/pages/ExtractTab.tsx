import { useState } from 'react';
import DropZone from '../components/DropZone';
import FileChip from '../components/FileChip';
import StatusMessage from '../components/StatusMessage';
import DocResultCard from '../components/DocResultCard';
import * as api from '../lib/api';

interface ExtractResult {
  filename: string;
  extracted: Record<string, unknown> | null;
  sourceFile: string;
  docType: string;
  error?: string;
}

interface ExtractTabProps {
  schemas: string[];
  dbConfig: { dialect: string; tableName: string; schemaName: string; connStr: string; includeDdl: boolean };
  onGroundTruthSaved?: () => void;
}

export default function ExtractTab({ schemas, dbConfig, onGroundTruthSaved }: ExtractTabProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [docType, setDocType] = useState(schemas[0] || '');
  const [customSchema, setCustomSchema] = useState('');
  const [status, setStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [results, setResults] = useState<ExtractResult[]>([]);
  const [extracting, setExtracting] = useState(false);

  const handleFiles = (newFiles: File[]) => {
    const pdfs = newFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'));
    setFiles(prev => [...prev, ...pdfs]);
  };

  const removeFile = (idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const handleExtract = async () => {
    if (!files.length) return;
    setExtracting(true);
    setResults([]);
    setStatus({ msg: `Extracting ${files.length} document(s)...`, type: 'loading' });

    const newResults: ExtractResult[] = [];
    for (let i = 0; i < files.length; i++) {
      setStatus({ msg: `Extracting ${i + 1}/${files.length}...`, type: 'loading' });
      try {
        const data = await api.extractPdf(files[i], docType, customSchema || undefined);
        newResults.push({
          filename: files[i].name,
          extracted: data.extracted,
          sourceFile: data.source_file,
          docType: data.doc_type,
        });
      } catch (e: unknown) {
        newResults.push({
          filename: files[i].name,
          extracted: null,
          sourceFile: '',
          docType,
          error: e instanceof Error ? e.message : 'Extraction failed',
        });
      }
      setResults([...newResults]);
    }

    setStatus({ msg: `Done. ${newResults.length} document(s) extracted.`, type: 'success' });
    setFiles([]);
    setExtracting(false);
  };

  return (
    <div>
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Upload & Extract</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Document Type</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
            >
              {schemas.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Custom Schema (optional)</label>
            <input
              type="text"
              value={customSchema}
              onChange={(e) => setCustomSchema(e.target.value)}
              placeholder='{"properties":{...}}'
              className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
            />
          </div>
        </div>

        <DropZone accept=".pdf" multiple onFiles={handleFiles}>
          <p className="text-[0.8125rem] font-light">
            Drop PDFs here or <strong className="font-medium text-silver">click to browse</strong>
          </p>
        </DropZone>

        {files.length > 0 && (
          <div className="mb-5">
            {files.map((f, i) => <FileChip key={`${f.name}-${i}`} name={f.name} onRemove={() => removeFile(i)} />)}
          </div>
        )}

        <button
          onClick={handleExtract}
          disabled={files.length === 0 || extracting}
          className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Extract All
        </button>

        <StatusMessage message={status.msg} type={status.type} />
      </div>

      {results.length > 0 && (
        <div>
          {results.map((r, i) => (
            <DocResultCard
              key={`${r.filename}-${i}`}
              filename={r.filename}
              extracted={r.extracted}
              sourceFile={r.sourceFile}
              docType={r.docType}
              error={r.error}
              dbConfig={dbConfig}
              onGroundTruthSaved={onGroundTruthSaved}
            />
          ))}
        </div>
      )}
    </div>
  );
}
