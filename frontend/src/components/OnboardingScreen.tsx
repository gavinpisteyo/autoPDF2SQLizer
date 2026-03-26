import { useState } from 'react';
import type { ApiClient } from '../lib/api';

interface OnboardingScreenProps {
  api: ApiClient;
  userName: string;
  onOrgCreated: (orgId: string) => void;
  onJoinRequested: () => void;
}

export default function OnboardingScreen({ api, userName, onOrgCreated, onJoinRequested }: OnboardingScreenProps) {
  const [mode, setMode] = useState<'choose' | 'create' | 'join'>('choose');
  const [orgName, setOrgName] = useState('');
  const [joinOrgId, setJoinOrgId] = useState('');
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!orgName.trim()) return setMsg('Enter an organization name');
    setLoading(true);
    setMsg('');
    try {
      const org = await api.createOrg(orgName.trim());
      onOrgCreated(org.id);
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'Failed to create organization');
    }
    setLoading(false);
  };

  const handleJoin = async () => {
    if (!joinOrgId.trim()) return setMsg('Enter an organization ID');
    setLoading(true);
    setMsg('');
    try {
      await api.requestJoinOrg(joinOrgId.trim());
      setMsg('Request sent! An admin will review your request.');
      onJoinRequested();
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : 'Failed to send request');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center">
      <div className="max-w-md w-full px-4">
        <div className="text-center mb-10">
          <h1 className="font-heading text-2xl font-semibold text-cloud tracking-tight mb-1">
            Welcome{userName ? `, ${userName.split(' ')[0]}` : ''}
          </h1>
          <p className="text-coral text-sm font-medium mb-4">autoPDF2SQLizer by Pisteyo</p>
          <p className="text-mid text-sm font-light leading-relaxed">
            Get started by creating a new organization or joining an existing one.
          </p>
        </div>

        {mode === 'choose' && (
          <div className="space-y-3">
            <button
              onClick={() => setMode('create')}
              className="w-full p-5 text-left bg-surface border border-border rounded-lg
                         hover:border-coral/30 transition-colors group"
            >
              <h3 className="text-sm font-medium text-cloud group-hover:text-coral transition-colors">
                Create Organization
              </h3>
              <p className="text-xs text-mid mt-1">Start a new org — you'll be the admin.</p>
            </button>

            <button
              onClick={() => setMode('join')}
              className="w-full p-5 text-left bg-surface border border-border rounded-lg
                         hover:border-coral/30 transition-colors group"
            >
              <h3 className="text-sm font-medium text-cloud group-hover:text-coral transition-colors">
                Join an Organization
              </h3>
              <p className="text-xs text-mid mt-1">Enter an org ID to request access. An admin will approve you.</p>
            </button>
          </div>
        )}

        {mode === 'create' && (
          <div className="bg-surface border border-border rounded-lg p-6">
            <h2 className="text-sm font-medium text-cloud mb-4">Create Organization</h2>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
              Organization Name
            </label>
            <input
              type="text"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="e.g. Acme Corp"
              autoFocus
              className="w-full px-3 py-2.5 text-sm bg-black border border-border-strong rounded-md text-silver mb-4
                         outline-none focus:border-coral transition-colors"
            />
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                disabled={loading}
                className="flex-1 px-5 py-2.5 text-sm font-medium bg-coral text-white rounded-md
                           hover:bg-coral-muted active:translate-y-px transition-all
                           disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {loading ? 'Creating...' : 'Create'}
              </button>
              <button
                onClick={() => { setMode('choose'); setMsg(''); }}
                className="px-4 py-2.5 text-sm font-medium bg-transparent border border-border-strong text-mid rounded-md
                           hover:bg-white/[0.04] transition-colors"
              >
                Back
              </button>
            </div>
            {msg && <p className="text-xs text-rose mt-3">{msg}</p>}
          </div>
        )}

        {mode === 'join' && (
          <div className="bg-surface border border-border rounded-lg p-6">
            <h2 className="text-sm font-medium text-cloud mb-4">Join Organization</h2>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
              Organization ID
            </label>
            <input
              type="text"
              value={joinOrgId}
              onChange={(e) => setJoinOrgId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleJoin()}
              placeholder="Ask your admin for the org ID"
              autoFocus
              className="w-full px-3 py-2.5 text-sm bg-black border border-border-strong rounded-md text-silver mb-4
                         outline-none focus:border-coral transition-colors"
            />
            <div className="flex gap-2">
              <button
                onClick={handleJoin}
                disabled={loading}
                className="flex-1 px-5 py-2.5 text-sm font-medium bg-coral text-white rounded-md
                           hover:bg-coral-muted active:translate-y-px transition-all
                           disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {loading ? 'Sending...' : 'Request Access'}
              </button>
              <button
                onClick={() => { setMode('choose'); setMsg(''); }}
                className="px-4 py-2.5 text-sm font-medium bg-transparent border border-border-strong text-mid rounded-md
                           hover:bg-white/[0.04] transition-colors"
              >
                Back
              </button>
            </div>
            {msg && <p className="text-xs mt-3" style={{ color: msg.includes('sent') ? 'var(--color-sage)' : 'var(--color-rose)' }}>{msg}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
