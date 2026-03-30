interface SchemaProperty {
  type?: string;
  properties?: Record<string, SchemaProperty>;
  [key: string]: unknown;
}

interface NestedResultsTableProps {
  fieldName: string;
  items: Record<string, unknown>[];
  itemSchema: SchemaProperty;
  onChange: (updatedItems: Record<string, unknown>[]) => void;
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return value.toLocaleString();
  return String(value);
}

function parseCellValue(raw: string, type?: string): unknown {
  if (raw === '') return null;
  if (type === 'number' || type === 'integer') {
    const n = Number(raw.replace(/,/g, ''));
    return isNaN(n) ? raw : n;
  }
  if (type === 'boolean') return raw === 'true';
  return raw;
}

export default function NestedResultsTable({ fieldName, items, itemSchema, onChange }: NestedResultsTableProps) {
  const properties = itemSchema.properties || {};
  const columns = Object.keys(properties);

  if (columns.length === 0 || items.length === 0) return null;

  const handleCellChange = (rowIndex: number, key: string, value: string) => {
    const propSchema = properties[key];
    const parsed = parseCellValue(value, propSchema?.type);
    const updatedItems = items.map((item, i) =>
      i === rowIndex ? { ...item, [key]: parsed } : item,
    );
    onChange(updatedItems);
  };

  const handleAddRow = () => {
    const emptyRow: Record<string, unknown> = {};
    for (const key of columns) {
      emptyRow[key] = null;
    }
    onChange([...items, emptyRow]);
  };

  const handleRemoveRow = (index: number) => {
    onChange(items.filter((_, i) => i !== index));
  };

  return (
    <div className="mt-3 mb-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-medium text-mid uppercase tracking-wide">
          {formatLabel(fieldName)}
        </h4>
        <button
          onClick={handleAddRow}
          className="text-xs text-coral hover:text-coral-muted transition-colors"
        >
          + Add Row
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem] border-collapse">
          <thead>
            <tr>
              {columns.map(col => (
                <th
                  key={col}
                  className="text-left text-[0.6875rem] text-mid uppercase tracking-wide pb-2 pr-3 border-b border-border font-medium"
                >
                  {formatLabel(col)}
                </th>
              ))}
              <th className="pb-2 border-b border-border w-8" />
            </tr>
          </thead>
          <tbody>
            {items.map((item, rowIdx) => (
              <tr key={rowIdx} className="border-b border-border/50">
                {columns.map(col => (
                  <td key={col} className="py-1.5 pr-3">
                    <input
                      type="text"
                      value={formatCellValue(item[col])}
                      onChange={(e) => handleCellChange(rowIdx, col, e.target.value)}
                      className="w-full px-2 py-1.5 text-sm bg-deep border border-border-strong rounded text-silver
                                 outline-none focus:border-coral transition-colors"
                    />
                  </td>
                ))}
                <td className="py-1.5">
                  <button
                    onClick={() => handleRemoveRow(rowIdx)}
                    className="text-mid hover:text-rose transition-colors text-sm font-semibold px-1"
                    title="Remove row"
                  >
                    &times;
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
