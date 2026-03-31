import { useState } from 'react';
import NestedResultsTable from './NestedResultsTable';

interface SchemaProperty {
  type?: string;
  items?: SchemaProperty;
  properties?: Record<string, SchemaProperty>;
  [key: string]: unknown;
}

interface ResultsTableProps {
  data: Record<string, unknown>;
  schema: Record<string, SchemaProperty>;
  onSave: (correctedData: Record<string, unknown>) => void;
  saving: boolean;
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatDisplayValue(value: unknown, type?: string): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') {
    if (type === 'integer') return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    return value.toLocaleString();
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function parseCellValue(raw: string, type?: string): unknown {
  if (raw === '') return null;
  if (type === 'number' || type === 'integer') {
    const n = Number(raw.replace(/,/g, ''));
    return isNaN(n) ? raw : n;
  }
  if (type === 'boolean') return raw.toLowerCase() === 'true' || raw.toLowerCase() === 'yes';
  return raw;
}

export default function ResultsTable({ data, schema, onSave, saving }: ResultsTableProps) {
  const [editedData, setEditedData] = useState<Record<string, unknown>>({ ...data });
  const [newFieldName, setNewFieldName] = useState('');
  const [showAddField, setShowAddField] = useState(false);

  const scalarFields: string[] = [];
  const arrayFields: string[] = [];

  // Include schema fields AND any extra fields in the data
  const allKeys = new Set([...Object.keys(schema), ...Object.keys(editedData)]);
  for (const key of allKeys) {
    const prop = schema[key];
    if (prop?.type === 'array' && prop.items?.properties) {
      arrayFields.push(key);
    } else {
      scalarFields.push(key);
    }
  }

  const handleFieldChange = (key: string, value: string) => {
    const prop = schema[key];
    const parsed = parseCellValue(value, prop?.type);
    setEditedData(prev => ({ ...prev, [key]: parsed }));
  };

  const handleRemoveField = (key: string) => {
    setEditedData(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleAddField = () => {
    if (!newFieldName.trim()) return;
    const key = newFieldName.trim().toLowerCase().replace(/\s+/g, '_');
    setEditedData(prev => ({ ...prev, [key]: '' }));
    setNewFieldName('');
    setShowAddField(false);
  };

  const handleArrayChange = (key: string, updatedItems: Record<string, unknown>[]) => {
    setEditedData(prev => ({ ...prev, [key]: updatedItems }));
  };

  const handleSave = () => {
    onSave(editedData);
  };

  return (
    <div>
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Review Extracted Data
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Edit any fields that need correction. Add missing fields with the button below.
      </p>

      {/* Scalar fields as a table */}
      {scalarFields.length > 0 && (
        <div className="overflow-x-auto mb-3">
          <table className="w-full text-[0.8125rem] border-collapse">
            <thead>
              <tr>
                <th className="text-left text-[0.6875rem] text-mid uppercase tracking-wide pb-2 pr-4 border-b border-border font-medium w-1/3">
                  Field
                </th>
                <th className="text-left text-[0.6875rem] text-mid uppercase tracking-wide pb-2 border-b border-border font-medium">
                  Value
                </th>
                <th className="w-10 border-b border-border" />
              </tr>
            </thead>
            <tbody>
              {scalarFields.map(key => (
                <tr key={key} className="border-b border-border/50">
                  <td className="py-2.5 pr-4 text-silver font-medium">
                    {formatLabel(key)}
                  </td>
                  <td className="py-2.5">
                    <input
                      type="text"
                      value={formatDisplayValue(editedData[key], schema[key]?.type)}
                      onChange={(e) => handleFieldChange(key, e.target.value)}
                      className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver
                                 outline-none focus:border-coral transition-colors"
                    />
                  </td>
                  <td className="py-2.5 text-center">
                    {!schema[key] && (
                      <button
                        onClick={() => handleRemoveField(key)}
                        className="text-mid hover:text-red-400 transition-colors text-xs"
                        title="Remove field"
                      >
                        &times;
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add field button */}
      {showAddField ? (
        <div className="flex gap-2 mb-5">
          <input
            type="text"
            value={newFieldName}
            onChange={(e) => setNewFieldName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddField()}
            placeholder="Field name (e.g. quarter_4_ebitda)"
            className="flex-1 px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver
                       outline-none focus:border-coral transition-colors"
            autoFocus
          />
          <button onClick={handleAddField} className="px-3 py-2 text-xs font-medium bg-coral text-white rounded-md hover:bg-coral-muted transition-all">
            Add
          </button>
          <button onClick={() => { setShowAddField(false); setNewFieldName(''); }} className="px-3 py-2 text-xs font-medium text-mid hover:text-silver transition-colors">
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowAddField(true)}
          className="mb-5 text-[0.8125rem] text-coral hover:underline transition-colors"
        >
          + Add a field
        </button>
      )}

      {/* Array fields as sub-tables */}
      {arrayFields.map(key => {
        const items = Array.isArray(editedData[key]) ? editedData[key] as Record<string, unknown>[] : [];
        const itemSchema = schema[key]?.items as SchemaProperty;

        return (
          <NestedResultsTable
            key={key}
            fieldName={key}
            items={items}
            itemSchema={itemSchema}
            onChange={(updated) => handleArrayChange(key, updated)}
          />
        );
      })}

      <button
        onClick={handleSave}
        disabled={saving}
        className="mt-4 px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                   hover:bg-coral-muted active:translate-y-px transition-all
                   disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {saving ? 'Saving...' : 'Save Corrections'}
      </button>
    </div>
  );
}
