import { useState } from 'react';
import StatusMessage from '../components/StatusMessage';
import * as api from '../lib/api';

interface DatabaseTabProps {
  config: {
    dialect: string;
    tableName: string;
    schemaName: string;
    connStr: string;
    includeDdl: boolean;
  };
  onChange: (config: DatabaseTabProps['config']) => void;
}

export default function DatabaseTab({ config, onChange }: DatabaseTabProps) {
  const [testStatus, setTestStatus] = useState<{ msg: string; type: 'success' | 'error' | 'loading' | null }>({ msg: '', type: null });

  const update = (field: string, value: string | boolean) => {
    onChange({ ...config, [field]: value });
  };

  const handleTest = async () => {
    if (!config.connStr) return setTestStatus({ msg: 'Enter a connection string', type: 'error' });
    setTestStatus({ msg: 'Testing...', type: 'loading' });
    try {
      const data = await api.testConnection(config.connStr);
      setTestStatus({ msg: data.message, type: data.status === 'ok' ? 'success' : 'error' });
    } catch (e: unknown) {
      setTestStatus({ msg: e instanceof Error ? e.message : 'Test failed', type: 'error' });
    }
  };

  return (
    <div>
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Connection</h2>
        <p className="text-[0.8125rem] text-mid font-light mb-5">
          Configure your database connection for uploading extracted data.
        </p>

        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Dialect</label>
        <select
          value={config.dialect}
          onChange={(e) => update('dialect', e.target.value)}
          className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-5 outline-none focus:border-coral transition-colors"
        >
          <option value="mssql">SQL Server</option>
          <option value="postgres">PostgreSQL</option>
          <option value="mysql">MySQL</option>
        </select>

        <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Connection String</label>
        <input
          type="text"
          value={config.connStr}
          onChange={(e) => update('connStr', e.target.value)}
          placeholder="mssql+pymssql://user:pass@server/database"
          className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-2 outline-none focus:border-coral transition-colors"
        />
        <p className="text-[0.75rem] text-mid mb-5 flex flex-wrap gap-3">
          <code className="font-mono text-xs text-silver bg-white/[0.04] px-1.5 py-0.5 rounded-sm">mssql+pymssql://user:pass@server/db</code>
          <code className="font-mono text-xs text-silver bg-white/[0.04] px-1.5 py-0.5 rounded-sm">postgresql://user:pass@host:5432/db</code>
        </p>

        <button
          onClick={handleTest}
          className="px-5 py-2 text-[0.8125rem] font-medium bg-coral text-white rounded-md hover:bg-coral-muted active:translate-y-px transition-all"
        >
          Test Connection
        </button>
        <StatusMessage message={testStatus.msg} type={testStatus.type} />
      </div>

      <div className="h-px bg-border my-10" />

      <div>
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">SQL Settings</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
          <div>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Target Table</label>
            <input
              type="text"
              value={config.tableName}
              onChange={(e) => update('tableName', e.target.value)}
              placeholder="e.g. Invoices"
              className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Schema / Owner</label>
            <input
              type="text"
              value={config.schemaName}
              onChange={(e) => update('schemaName', e.target.value)}
              className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver outline-none focus:border-coral transition-colors"
            />
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer text-[0.8125rem] text-silver">
          <input
            type="checkbox"
            checked={config.includeDdl}
            onChange={(e) => update('includeDdl', e.target.checked)}
            className="accent-silver"
          />
          Include CREATE TABLE statement
        </label>
      </div>
    </div>
  );
}
