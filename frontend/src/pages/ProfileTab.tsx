import { useEffect, useState } from 'react';
import { useAuthContext, AUTH_ENABLED } from '../lib/auth';
import type { ApiClient } from '../lib/api';

interface ProfileTabProps {
  api: ApiClient;
}

interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  member_count: number;
  created_at: string;
}

interface JoinReq {
  id: string;
  user_email: string;
  user_name: string;
  requested_at: string;
}

function DbStatusCard({ api, orgId }: { api: ApiClient; orgId: string }) {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!orgId) return;
    api.getDbStatus(orgId).then(setStatus).catch(() => {});
  }, [api, orgId]);

  if (!status) return null;

  const s = status.status as string;
  const badge = s === 'ready'
    ? 'bg-sage-bg text-sage'
    : s === 'provisioning'
    ? 'bg-coral/15 text-coral'
    : s === 'failed'
    ? 'bg-red-500/15 text-red-400'
    : 'bg-white/[0.06] text-mid';

  return (
    <div className="mt-6">
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-cloud">Database</h3>
          <span className={`text-[0.6875rem] font-semibold uppercase tracking-wider px-2.5 py-1 rounded-sm ${badge}`}>
            {s === 'sqlite_fallback' ? 'Local (SQLite)' : s}
          </span>
        </div>
        {s === 'ready' && (
          <p className="text-xs text-mid">
            Azure SQL Database <span className="text-silver font-mono">{status.database_name as string}</span> is active.
          </p>
        )}
        {s === 'provisioning' && (
          <p className="text-xs text-mid">Database is being provisioned. This usually takes 10-30 seconds.</p>
        )}
        {s === 'failed' && (
          <p className="text-xs text-red-400">Provisioning failed: {status.error as string}</p>
        )}
        {s === 'sqlite_fallback' && (
          <p className="text-xs text-mid">Azure SQL is not configured. Using local SQLite for development.</p>
        )}
      </div>
    </div>
  );
}

const ROLE_LABELS: Record<string, { label: string; desc: string }> = {
  org_admin: { label: 'Admin', desc: 'Full access — manage org, projects, execute SQL, all features' },
  developer: { label: 'Developer', desc: 'Ground truth, evaluation, DB connections, extraction' },
  business_user: { label: 'Business User', desc: 'Upload & extract PDFs, create schemas, manage ground truth' },
  viewer: { label: 'Viewer', desc: 'Read-only access to schemas and extraction results' },
};

export default function ProfileTab({ api }: ProfileTabProps) {
  const { user, orgId, role, logout, setProjectId } = useAuthContext();
  const roleInfo = ROLE_LABELS[role] || { label: role, desc: '' };
  const isAdmin = role === 'org_admin';

  // Projects
  const [projects, setProjects] = useState<Project[]>([]);
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [projectMsg, setProjectMsg] = useState('');

  // Join org
  const [joinOrgId, setJoinOrgId] = useState('');
  const [joinMsg, setJoinMsg] = useState('');

  // Admin: join requests
  const [requests, setRequests] = useState<JoinReq[]>([]);

  const loadProjects = async () => {
    try { setProjects(await api.listProjects()); } catch {}
  };

  const loadRequests = async () => {
    if (!isAdmin) return;
    try { setRequests(await api.listJoinRequests()); } catch {}
  };

  useEffect(() => { loadProjects(); loadRequests(); }, [api]);

  const handleCreateProject = async () => {
    if (!newName.trim() || !newSlug.trim()) return setProjectMsg('Name and slug required');
    try {
      const p = await api.createProject(newName.trim(), newSlug.trim(), newDesc.trim());
      setProjectMsg(`Created: ${p.name}`);
      setNewName(''); setNewSlug(''); setNewDesc('');
      loadProjects();
    } catch (e: unknown) {
      setProjectMsg(e instanceof Error ? e.message : 'Failed');
    }
  };

  const handleJoinOrg = async () => {
    if (!joinOrgId.trim()) return setJoinMsg('Enter an org ID');
    try {
      await api.requestJoinOrg(joinOrgId.trim());
      setJoinMsg('Request sent — waiting for admin approval');
      setJoinOrgId('');
    } catch (e: unknown) {
      setJoinMsg(e instanceof Error ? e.message : 'Failed');
    }
  };

  const handleResolve = async (requestId: string, approve: boolean) => {
    try {
      await api.resolveJoinRequest(requestId, approve);
      loadRequests();
    } catch {}
  };

  return (
    <div>
      {/* User Info */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Profile</h2>
        <div className="bg-surface border border-border rounded-lg p-6">
          <div className="flex items-start gap-5">
            {user?.picture ? (
              <img src={user.picture} alt="" className="w-16 h-16 rounded-full flex-shrink-0" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-charcoal flex items-center justify-center flex-shrink-0">
                <span className="text-2xl font-heading font-semibold text-cloud">
                  {(user?.name || '?')[0].toUpperCase()}
                </span>
              </div>
            )}
            <div className="flex-1 min-w-0">
              <h3 className="font-heading text-lg font-semibold text-cloud tracking-tight">
                {user?.name || 'Unknown'}
              </h3>
              <p className="text-sm text-mid mt-0.5">{user?.email || ''}</p>
              <div className="flex items-center gap-3 mt-3">
                <span className="px-3 py-1 text-xs font-medium bg-coral/10 text-coral rounded-md">
                  {roleInfo.label}
                </span>
                <span className="text-xs text-mid">{roleInfo.desc}</span>
              </div>
              {AUTH_ENABLED && (
                <button
                  onClick={logout}
                  className="mt-3 px-4 py-1.5 text-xs font-medium bg-transparent border border-border-strong
                             text-mid rounded-md hover:bg-white/[0.04] hover:text-silver transition-colors"
                >
                  Sign Out
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="h-px bg-border my-10" />

      {/* Organization */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Organization</h2>
        <div className="bg-surface border border-border rounded-lg p-6 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-coral/10 flex items-center justify-center flex-shrink-0">
              <span className="text-sm font-heading font-semibold text-coral">
                {(orgId || '?')[0].toUpperCase()}
              </span>
            </div>
            <div>
              <h3 className="text-sm font-medium text-cloud">{orgId || 'No organization'}</h3>
              <p className="text-xs text-mid">Active organization</p>
            </div>
          </div>
        </div>

        {/* Join another org */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-sm font-medium text-cloud mb-3">Join an Organization</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={joinOrgId}
              onChange={(e) => setJoinOrgId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleJoinOrg()}
              placeholder="Enter org ID"
              className="flex-1 px-3 py-2 text-sm bg-black border border-border-strong rounded-md text-silver
                         outline-none focus:border-coral transition-colors"
            />
            <button
              onClick={handleJoinOrg}
              className="px-4 py-2 text-sm font-medium bg-coral text-white rounded-md
                         hover:bg-coral-muted active:translate-y-px transition-all"
            >
              Request
            </button>
          </div>
          {joinMsg && <p className="text-xs text-sage mt-2">{joinMsg}</p>}
        </div>
      </div>

      {/* Database Status (admin only) */}
      {isAdmin && <DbStatusCard api={api} orgId={orgId || ''} />}

      <div className="h-px bg-border my-10" />

      {/* Projects */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Projects</h2>

        {projects.length === 0 ? (
          <p className="text-sm text-mid mb-4">No projects yet{isAdmin ? ' — create one below.' : '.'}</p>
        ) : (
          <div className="space-y-2 mb-6">
            {projects.map(p => (
              <div key={p.id} className="bg-surface border border-border rounded-lg p-4 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-cloud">{p.name}</h3>
                  <p className="text-xs text-mid">
                    {p.slug} &middot; {p.member_count} member{p.member_count !== 1 ? 's' : ''}
                    {p.description && ` — ${p.description}`}
                  </p>
                </div>
                <button
                  onClick={() => setProjectId(p.id)}
                  className="px-3 py-1.5 text-xs font-medium bg-transparent border border-border-strong
                             text-silver rounded-md hover:bg-white/[0.04] hover:border-white/15 transition-all"
                >
                  Open
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Create project (admin only) */}
        {isAdmin && (
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-sm font-medium text-cloud mb-3">Create Project</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1">Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => { setNewName(e.target.value); setNewSlug(e.target.value.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '')); }}
                  placeholder="e.g. Accounting"
                  className="w-full px-3 py-2 text-sm bg-black border border-border-strong rounded-md text-silver
                             outline-none focus:border-coral transition-colors"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1">Slug</label>
                <input
                  type="text"
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                  placeholder="accounting"
                  className="w-full px-3 py-2 text-sm bg-black border border-border-strong rounded-md text-silver
                             outline-none focus:border-coral transition-colors"
                />
              </div>
            </div>
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1">Description (optional)</label>
            <input
              type="text"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="e.g. Invoice and expense report processing"
              className="w-full px-3 py-2 text-sm bg-black border border-border-strong rounded-md text-silver mb-3
                         outline-none focus:border-coral transition-colors"
            />
            <button
              onClick={handleCreateProject}
              className="px-5 py-2 text-sm font-medium bg-coral text-white rounded-md
                         hover:bg-coral-muted active:translate-y-px transition-all"
            >
              Create Project
            </button>
            {projectMsg && <p className="text-xs text-sage mt-2">{projectMsg}</p>}
          </div>
        )}
      </div>

      {/* Admin: Join Requests */}
      {isAdmin && (
        <>
          <div className="h-px bg-border my-10" />
          <div>
            <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">
              Pending Join Requests
            </h2>
            {requests.length === 0 ? (
              <p className="text-sm text-mid">No pending requests.</p>
            ) : (
              <div className="space-y-2">
                {requests.map(r => (
                  <div key={r.id} className="bg-surface border border-border rounded-lg p-4 flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-medium text-cloud">{r.user_name || r.user_email}</h3>
                      <p className="text-xs text-mid">{r.user_email} &middot; {new Date(r.requested_at).toLocaleDateString()}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleResolve(r.id, true)}
                        className="px-3 py-1.5 text-xs font-medium bg-sage/20 text-sage rounded-md
                                   hover:bg-sage/30 transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleResolve(r.id, false)}
                        className="px-3 py-1.5 text-xs font-medium bg-rose/20 text-rose rounded-md
                                   hover:bg-rose/30 transition-colors"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
