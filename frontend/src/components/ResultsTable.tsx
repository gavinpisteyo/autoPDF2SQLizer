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

/** Build initial data: start with all schema fields (empty if not in extraction) then overlay extracted values */
function buildInitialData(data: Record<string, unknown>, schema: Record<string, SchemaProperty>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  // First: all schema fields with defaults
  for (const key of Object.keys(schema)) {
    const prop = schema[key];
    if (prop.type === 'array') {
      result[key] = [];
    } else {
      result[key] = null;
    }
  }
  // Then: overlay with extracted data
  for (const [key, value] of Object.entries(data)) {
    result[key] = value;
  }
  return result;
}

export default function ResultsTable({ data, schema, onSave, saving }: ResultsTableProps) {
  const [editedData, setEditedData] = useState<Record<string, unknown>>(() => buildInitialData(data, schema));
  const [newFieldName, setNewFieldName] = useState('');
  const [showAddField, setShowAddField] = useState(false);
  // Track which fields have multiple values (user added extras)
  const [multiValues, setMultiValues] = useState<Record<string, string[]>>({});

  const scalarFields: string[] = [];
  const arrayFields: string[] = [];

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

  const handleMultiValueChange = (key: string, index: number, value: string) => {
    setMultiValues(prev => {
      const updated = [...(prev[key] || [])];
      updated[index] = value;
      return { ...prev, [key]: updated };
    });
  };

  const handleAddValue = (key: string) => {
    setMultiValues(prev => ({
      ...prev,
      [key]: [...(prev[key] || []), ''],
    }));
  };

  const handleRemoveValue = (key: string, index: number) => {
    setMultiValues(prev => {
      const updated = [...(prev[key] || [])];
      updated.splice(index, 1);
      return { ...prev, [key]: updated };
    });
  };

  const handleRemoveField = (key: string) => {
    setEditedData(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setMultiValues(prev => {
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
    // Merge multi-values into the data as arrays
    const finalData = { ...editedData };
    for (const [key, extras] of Object.entries(multiValues)) {
      if (extras.length > 0) {
        const prop = schema[key];
        const mainVal = finalData[key];
        const allVals = [mainVal, ...extras.map(v => parseCellValue(v, prop?.type))].filter(v => v !== null && v !== '');
        finalData[key] = allVals.length === 1 ? allVals[0] : allVals;
      }
    }
    onSave(finalData);
  };

  return (
    <div>
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Review Extracted Data
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Edit any fields that need correction. Use "+" to add extra values for a field, or add entirely new fields below.
      </p>

      {/* Scalar fields as a table */}
      {scalarFields.length > 0 && (
        <div className="overflow-x-auto mb-6">
          <table className="w-full text-[0.8125rem] border-collapse">
            <thead>
              <tr>
                <th className="text-left text-[0.6875rem] text-mid uppercase tracking-wide pb-2 pr-4 border-b border-border font-medium w-1/3">
                  Field
                </th>
                <th className="text-left text-[0.6875rem] text-mid uppercase tracking-wide pb-2 border-b border-border font-medium">
                  Value
                </th>
                <th className="w-20 border-b border-border" />
              </tr>
            </thead>
            <tbody>
              {scalarFields.map(key => {
                const extras = multiValues[key] || [];
                const isEmpty = editedData[key] === null || editedData[key] === undefined || editedData[key] === '';

                return (
                  <tr key={key} className="border-b border-border/50 align-top">
                    <td className="py-2.5 pr-4 text-silver font-medium">
                      {formatLabel(key)}
                      {isEmpty && schema[key] && (
                        <span className="block text-[0.625rem] text-mid/60 font-normal mt-0.5">Not found — fill in manually</span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <input
                        type="text"
                        value={formatDisplayValue(editedData[key], schema[key]?.type)}
                        onChange={(e) => handleFieldChange(key, e.target.value)}
                        placeholder={isEmpty ? `Enter ${formatLabel(key).toLowerCase()}...` : ''}
                        className={`w-full px-3 py-2 text-sm bg-deep border rounded-md text-silver
                                   outline-none focus:border-coral transition-colors ${
                                     isEmpty ? 'border-coral/30 bg-coral/[0.03]' : 'border-border-strong'
                                   }`}
                      />
                      {/* Extra values for this field */}
                      {extras.map((val, i) => (
                        <div key={i} className="flex gap-1.5 mt-1.5">
                          <input
                            type="text"
                            value={val}
                            onChange={(e) => handleMultiValueChange(key, i, e.target.value)}
                            placeholder={`Additional ${formatLabel(key).toLowerCase()}...`}
                            className="flex-1 px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver
                                       outline-none focus:border-coral transition-colors"
                          />
                          <button
                            onClick={() => handleRemoveValue(key, i)}
                            className="px-2 text-mid hover:text-red-400 transition-colors text-sm"
                            title="Remove value"
                          >
                            &times;
                          </button>
                        </div>
                      ))}
                    </td>
                    <td className="py-2.5 flex gap-1 justify-end">
                      <button
                        onClick={() => handleAddValue(key)}
                        className="px-2 py-1 text-[0.625rem] font-medium text-coral hover:bg-coral/10 rounded transition-colors"
                        title="Add another value for this field"
                      >
                        + value
                      </button>
                      {!schema[key] && (
                        <button
                          onClick={() => handleRemoveField(key)}
                          className="px-2 py-1 text-mid hover:text-red-400 transition-colors text-xs"
                          title="Remove field"
                        >
                          &times;
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Add field — separated from save with spacing */}
      <div className="mb-8 pb-6 border-b border-border">
        {showAddField ? (
          <div className="flex gap-2">
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
            <button onClick={handleAddField} className="px-4 py-2 text-xs font-medium bg-coral text-white rounded-md hover:bg-coral-muted transition-all">
              Add Field
            </button>
            <button onClick={() => { setShowAddField(false); setNewFieldName(''); }} className="px-3 py-2 text-xs font-medium text-mid hover:text-silver transition-colors">
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowAddField(true)}
            className="text-[0.8125rem] text-coral hover:underline transition-colors"
          >
            + Add a new field
          </button>
        )}
      </div>

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

      {/* Save — clearly separated */}
      <div className="mt-8 pt-6 border-t border-border">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-3 text-sm font-semibold bg-coral text-white rounded-md
                     hover:bg-coral-muted active:translate-y-px transition-all
                     disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving...' : 'Save Corrections'}
        </button>
      </div>
    </div>
  );
}
