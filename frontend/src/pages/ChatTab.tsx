import { useEffect, useState, useRef } from 'react';
import type { ApiClient } from '../lib/api';

interface KbTableStat {
  name: string;
  rows: number;
}

interface KbStats {
  exists: boolean;
  tables: KbTableStat[];
  total_rows: number;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sql?: string;
  results?: Record<string, unknown>[];
  error?: string | null;
}

interface ChatTabProps {
  api: ApiClient;
}

export default function ChatTab({ api }: ChatTabProps) {
  const [stats, setStats] = useState<KbStats | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const loadStats = async () => {
    try {
      const data = await api.kbStats();
      setStats(data as KbStats);
    } catch {
      // Stats not available
    }
  };

  useEffect(() => { loadStats(); }, [api]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleQuery = async () => {
    if (!input.trim() || loading) return;
    const question = input.trim();
    setInput('');

    const userMsg: ChatMessage = { role: 'user', content: question };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const data = await api.kbQuery(question);
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.answer as string,
        sql: data.sql as string | undefined,
        results: data.results as Record<string, unknown>[] | undefined,
        error: data.error as string | null | undefined,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (e: unknown) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${e instanceof Error ? e.message : 'Unknown error'}`,
        error: e instanceof Error ? e.message : 'Unknown',
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* Stats */}
      <div className="mb-8">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Chat</h2>
        <p className="text-[0.8125rem] text-mid font-light mb-5">
          Query your extracted data using natural language. The system generates SQL, runs it, and explains the results.
        </p>

        {stats && stats.exists ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <div className="bg-surface border border-border-strong rounded-lg p-4">
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-1">Tables</div>
              <div className="text-lg font-semibold text-silver">{stats.tables.length}</div>
            </div>
            <div className="bg-surface border border-border-strong rounded-lg p-4">
              <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-1">Total Rows</div>
              <div className="text-lg font-semibold text-silver">{stats.total_rows.toLocaleString()}</div>
            </div>
            {stats.tables.map(t => (
              <div key={t.name} className="bg-surface border border-border-strong rounded-lg p-4">
                <div className="text-[0.6875rem] text-mid uppercase tracking-wide mb-1 truncate" title={t.name}>{t.name}</div>
                <div className="text-lg font-semibold text-silver">{t.rows.toLocaleString()} <span className="text-xs text-mid font-normal">rows</span></div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-surface border border-border-strong rounded-lg p-5 mb-6">
            <p className="text-[0.8125rem] text-mid">
              No data indexed yet. Extract documents in the Documents tab to get started.
            </p>
          </div>
        )}
      </div>

      {/* Chat interface */}
      <div>
        <h3 className="text-xs font-semibold text-silver uppercase tracking-wide mb-3">Ask Your Data</h3>

        <div className="bg-surface border border-border-strong rounded-lg overflow-hidden">
          {/* Message history */}
          <div className="max-h-96 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <p className="text-[0.8125rem] text-mid text-center py-8">
                Ask a question about your extracted data. Examples:<br />
                <span className="text-silver">"What's the total of all invoices?"</span><br />
                <span className="text-silver">"Show me contracts expiring this month"</span><br />
                <span className="text-silver">"Which vendor has the highest invoice total?"</span>
              </p>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-lg px-4 py-3 ${
                  msg.role === 'user'
                    ? 'bg-coral/15 text-silver'
                    : 'bg-white/[0.04] text-silver'
                }`}>
                  <p className="text-[0.8125rem] whitespace-pre-wrap">{msg.content}</p>

                  {msg.sql && (
                    <details className="mt-2">
                      <summary className="text-[0.6875rem] text-mid cursor-pointer hover:text-silver">
                        View SQL
                      </summary>
                      <pre className="mt-1 text-[0.75rem] font-mono text-mid bg-deep rounded p-2 overflow-x-auto">
                        {msg.sql}
                      </pre>
                    </details>
                  )}

                  {msg.results && msg.results.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-[0.6875rem] text-mid cursor-pointer hover:text-silver">
                        View raw results ({msg.results.length} rows)
                      </summary>
                      <pre className="mt-1 text-[0.75rem] font-mono text-mid bg-deep rounded p-2 overflow-x-auto max-h-48">
                        {JSON.stringify(msg.results.slice(0, 10), null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-white/[0.04] rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2 text-[0.8125rem] text-mid">
                    <div className="w-1.5 h-1.5 rounded-full bg-coral animate-pulse" />
                    Thinking...
                  </div>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Input */}
          <div className="border-t border-border p-3 flex gap-2">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleQuery(); } }}
              placeholder="Ask a question about your data..."
              disabled={loading || !stats?.exists}
              className="flex-1 px-3 py-2.5 text-sm bg-deep border border-border-strong rounded-md text-silver placeholder:text-mid/50
                         outline-none focus:border-coral transition-colors disabled:opacity-40"
            />
            <button
              onClick={handleQuery}
              disabled={loading || !input.trim() || !stats?.exists}
              className="px-5 py-2.5 text-[0.8125rem] font-medium bg-coral text-white rounded-md
                         hover:bg-coral-muted active:translate-y-px transition-all
                         disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Ask
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
