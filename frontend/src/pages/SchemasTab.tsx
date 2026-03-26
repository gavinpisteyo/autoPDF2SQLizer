import { useState } from 'react';
import StatusMessage from '../components/StatusMessage';
import * as api from '../lib/api';

interface SchemasTabProps {
  schemas: Record<string, { builtin: boolean }>;
  onSchemasChanged: () => void;
}

export default function SchemasTab({ schemas, onSchemasChanged }: SchemasTabProps) {
  const [genKey, setGenKey] = useState('');
  const [genDesc, setGenDesc] = useState('');
  const [genStatus, setGenStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [genOutput, setGenOutput] = useState('');
  const [generating, setGenerating] = useState(false);

  const [manualKey, setManualKey] = useState('');
  const [manualBody, setManualBody] = useState('');
  const [manualStatus, setManualStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });

  const handleGenerate = async () => {
    if (!genKey || !genDesc) return setGenStatus({ msg: 'Fill in both fields', type: 'error' });
    setGenerating(true);
    setGenStatus({ msg: 'Generating schema...', type: 'loading' });
    setGenOutput('');
    try {
      const data = await api.generateSchema(genDesc, genKey);
      setGenStatus({ msg: `Schema generated and saved as "${data.doc_type}"`, type: 'success' });
      setGenOutput(JSON.stringify(data.schema, null, 2));
      onSchemasChanged();
    } catch (e: unknown) {
      setGenStatus({ msg: e instanceof Error ? e.message : 'Generation failed', type: 'error' });
    }
    setGenerating(false);
  };

  const handleSaveGenOutput = async () => {
    if (!genKey || !genOutput) return;
    try {
      const schema = JSON.parse(genOutput);
      await api.saveSchema(genKey, schema);
      setGenStatus({ msg: `Schema "${genKey}" updated`, type: 'success' });
      onSchemasChanged();
    } catch (e: unknown) {
      setGenStatus({ msg: e instanceof Error ? e.message : 'Save failed', type: 'error' });
    }
  };

  const handleManualSave = async () => {
    if (!manualKey || !manualBody) return setManualStatus({ msg: 'Fill in both fields', type: 'error' });
    try {
      const schema = JSON.parse(manualBody);
      await api.saveSchema(manualKey, schema);
      setManualStatus({ msg: `Schema "${manualKey}" saved`, type: 'success' });
      onSchemasChanged();
    } catch (e: unknown) {
      setManualStatus({ msg: e instanceof Error ? e.message : 'Save failed', type: 'error' });
    }
  };

  return (
    <div>
      {/* Generate from description */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Describe What You Want</h2>
        <p className="text-[0.8125rem] text-mid font-light mb-5">
          Describe the fields you need in plain English. The schema is generated for you.
        </p>

        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Document Type Key</label>
        <input
          type="text"
          value={genKey}
          onChange={(e) => setGenKey(e.target.value)}
          placeholder="e.g. purchase_order"
          className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-5 outline-none focus:border-coral transition-colors"
        />

        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Describe the fields</label>
        <textarea
          value={genDesc}
          onChange={(e) => setGenDesc(e.target.value)}
          placeholder="I need the invoice number, vendor name, invoice date, each line item with description and amount, the subtotal, tax, and total."
          className="w-full min-h-[80px] font-sans text-sm bg-surface border border-border-strong rounded-md text-silver p-3 mb-5 resize-y outline-none focus:border-coral transition-colors"
        />

        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Generate Schema
        </button>
        <StatusMessage message={genStatus.msg} type={genStatus.type} />

        {genOutput && (
          <div className="mt-5">
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Generated Schema</label>
            <textarea
              value={genOutput}
              onChange={(e) => setGenOutput(e.target.value)}
              className="w-full min-h-[200px] font-mono text-[0.8125rem] leading-relaxed bg-surface border border-border-strong rounded-md text-silver p-3 mb-3 resize-y outline-none focus:border-coral transition-colors"
            />
            <button onClick={handleSaveGenOutput} className="px-5 py-2 text-[0.8125rem] font-medium bg-transparent border border-border-strong text-silver rounded-md hover:bg-white/[0.04] hover:border-white/15 active:translate-y-px transition-all">
              Save Schema
            </button>
          </div>
        )}
      </div>

      <div className="h-px bg-border my-10" />

      {/* Schema list */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Available Schemas</h2>
        {Object.keys(schemas).length === 0 ? (
          <p className="text-[0.8125rem] text-mid">No schemas yet.</p>
        ) : (
          <div>
            {Object.entries(schemas).map(([key, val]) => (
              <div key={key} className="flex justify-between items-center py-2.5 border-b border-border text-[0.8125rem]">
                <span>{key.replace(/_/g, ' ')}</span>
                <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-white/[0.04] text-mid">
                  {val.builtin ? 'built-in' : 'custom'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="h-px bg-border my-10" />

      {/* Manual JSON */}
      <div>
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Add Custom Schema</h2>
        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Document Type Key</label>
        <input
          type="text"
          value={manualKey}
          onChange={(e) => setManualKey(e.target.value)}
          placeholder="e.g. purchase_order"
          className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-5 outline-none focus:border-coral transition-colors"
        />
        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">JSON Schema</label>
        <textarea
          value={manualBody}
          onChange={(e) => setManualBody(e.target.value)}
          placeholder='{"type":"object","properties":{...}}'
          className="w-full min-h-[120px] font-mono text-[0.8125rem] leading-relaxed bg-surface border border-border-strong rounded-md text-silver p-3 mb-5 resize-y outline-none focus:border-coral transition-colors"
        />
        <button
          onClick={handleManualSave}
          className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all"
        >
          Save Schema
        </button>
        <StatusMessage message={manualStatus.msg} type={manualStatus.type} />
      </div>
    </div>
  );
}
