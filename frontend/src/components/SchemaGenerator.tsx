import { useState } from 'react';
import StatusMessage from './StatusMessage';
import type { ApiClient } from '../lib/api';

interface SchemaGeneratorProps {
  api: ApiClient;
  projectName: string;
  onSchemaGenerated: (docTypeKey: string, schema: Record<string, unknown>, projectId: string) => void;
}

export default function SchemaGenerator({ api, projectName, onSchemaGenerated }: SchemaGeneratorProps) {
  const [description, setDescription] = useState('');
  const [docTypeKey, setDocTypeKey] = useState(
    projectName.toLowerCase().replace(/[^\w]+/g, '_').replace(/^_|_$/g, ''),
  );
  const [generating, setGenerating] = useState(false);
  const [generatedSchema, setGeneratedSchema] = useState<Record<string, unknown> | null>(null);
  const [schemaPreview, setSchemaPreview] = useState('');
  const [status, setStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });
  const [confirming, setConfirming] = useState(false);

  const handleGenerate = async () => {
    if (!description.trim() || !docTypeKey.trim()) {
      setStatus({ msg: 'Fill in both the document type key and description', type: 'error' });
      return;
    }
    setGenerating(true);
    setStatus({ msg: 'Generating schema...', type: 'loading' });
    setGeneratedSchema(null);
    setSchemaPreview('');

    try {
      const data = await api.generateSchema(description.trim(), docTypeKey.trim());
      const schema = data.schema as Record<string, unknown>;
      setGeneratedSchema(schema);
      setSchemaPreview(JSON.stringify(schema, null, 2));
      setStatus({ msg: 'Schema generated. Review and confirm below.', type: 'success' });
    } catch (e: unknown) {
      setStatus({ msg: e instanceof Error ? e.message : 'Generation failed', type: 'error' });
    } finally {
      setGenerating(false);
    }
  };

  const handleConfirm = async () => {
    if (!generatedSchema || !docTypeKey.trim()) return;
    setConfirming(true);
    setStatus({ msg: 'Creating project and saving schema...', type: 'loading' });

    try {
      // Parse the preview in case user edited it
      const finalSchema = schemaPreview ? JSON.parse(schemaPreview) as Record<string, unknown> : generatedSchema;

      // Create the project
      const slug = projectName.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
      const project = await api.createProject(projectName, slug, '');

      // Save the schema
      await api.saveSchema(docTypeKey, finalSchema);

      setStatus({ msg: 'Project created and schema saved.', type: 'success' });
      onSchemaGenerated(docTypeKey, finalSchema, project.id as string);
    } catch (e: unknown) {
      setStatus({ msg: e instanceof Error ? e.message : 'Failed to create project', type: 'error' });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div>
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Define Schema for "{projectName}"
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Describe the fields you need in plain English. The schema is generated for you.
      </p>

      <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
        Document Type Key
      </label>
      <input
        type="text"
        value={docTypeKey}
        onChange={(e) => setDocTypeKey(e.target.value)}
        placeholder="e.g. purchase_order"
        className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-5
                   outline-none focus:border-coral transition-colors"
      />

      <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
        Describe the Fields
      </label>
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="I need the invoice number, vendor name, invoice date, each line item with description and amount, the subtotal, tax, and total."
        className="w-full min-h-[80px] font-sans text-sm bg-surface border border-border-strong rounded-md text-silver p-3 mb-5
                   resize-y outline-none focus:border-coral transition-colors"
      />

      <button
        onClick={handleGenerate}
        disabled={generating || !description.trim() || !docTypeKey.trim()}
        className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                   hover:bg-coral-muted active:translate-y-px transition-all
                   disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {generating ? 'Generating...' : 'Generate Schema'}
      </button>

      <StatusMessage message={status.msg} type={status.type} />

      {schemaPreview && (
        <div className="mt-5">
          <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
            Generated Schema
          </label>
          <textarea
            value={schemaPreview}
            onChange={(e) => setSchemaPreview(e.target.value)}
            className="w-full min-h-[200px] font-mono text-[0.8125rem] leading-relaxed bg-surface border border-border-strong rounded-md text-silver p-3 mb-4
                       resize-y outline-none focus:border-coral transition-colors"
          />
          <button
            onClick={handleConfirm}
            disabled={confirming}
            className="px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                       hover:bg-coral-muted active:translate-y-px transition-all
                       disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {confirming ? 'Creating...' : 'Confirm & Create Project'}
          </button>
        </div>
      )}
    </div>
  );
}
