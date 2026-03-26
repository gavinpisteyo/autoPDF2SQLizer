import { useCallback, useEffect, useState } from 'react';
import ExtractTab from './pages/ExtractTab';
import GroundTruthTab from './pages/GroundTruthTab';
import EvaluateTab from './pages/EvaluateTab';
import DatabaseTab from './pages/DatabaseTab';
import SchemasTab from './pages/SchemasTab';
import * as api from './lib/api';

const TABS = [
  { id: 'extract', label: 'Extract' },
  { id: 'ground-truth', label: 'Ground Truth' },
  { id: 'evaluate', label: 'Evaluate' },
  { id: 'database', label: 'Database' },
  { id: 'schemas', label: 'Schemas' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('extract');
  const [schemas, setSchemas] = useState<Record<string, { builtin: boolean }>>({});
  const [gtRefreshKey, setGtRefreshKey] = useState(0);
  const [dbConfig, setDbConfig] = useState({
    dialect: 'mssql',
    tableName: '',
    schemaName: 'dbo',
    connStr: '',
    includeDdl: false,
  });

  const loadSchemas = useCallback(async () => {
    try {
      const data = await api.listSchemas();
      setSchemas(data);
    } catch {}
  }, []);

  useEffect(() => { loadSchemas(); }, [loadSchemas]);

  const schemaKeys = Object.keys(schemas);

  return (
    <div className="max-w-[1000px] mx-auto px-8 pt-12 pb-16">
      {/* Header */}
      <div className="mb-12">
        <h1 className="font-heading text-xl font-semibold tracking-tight text-cloud">
          autoPDF2SQLizer <span className="font-normal text-coral">by Pisteyo</span>
        </h1>
        <p className="text-[0.8125rem] text-mid mt-1 font-light tracking-wide">
          Extract structured data from documents. Build accuracy. Push to your database.
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex border-b border-border mb-10">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              pr-6 py-3 text-[0.8125rem] font-medium border-b-[1.5px] -mb-px transition-colors
              ${activeTab === tab.id
                ? 'text-cloud border-coral'
                : 'text-mid border-transparent hover:text-silver'
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Panels */}
      {activeTab === 'extract' && (
        <ExtractTab
          schemas={schemaKeys}
          dbConfig={dbConfig}
          onGroundTruthSaved={() => setGtRefreshKey(k => k + 1)}
        />
      )}
      {activeTab === 'ground-truth' && (
        <GroundTruthTab schemas={schemaKeys} refreshKey={gtRefreshKey} />
      )}
      {activeTab === 'evaluate' && <EvaluateTab />}
      {activeTab === 'database' && (
        <DatabaseTab config={dbConfig} onChange={setDbConfig} />
      )}
      {activeTab === 'schemas' && (
        <SchemasTab schemas={schemas} onSchemasChanged={loadSchemas} />
      )}
    </div>
  );
}
