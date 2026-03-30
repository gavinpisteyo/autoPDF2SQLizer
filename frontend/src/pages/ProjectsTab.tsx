import { useEffect, useState } from 'react';
import { useAuthContext } from '../lib/auth';
import type { ApiClient } from '../lib/api';

interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  member_count: number;
  created_at: string;
  is_optimized?: boolean;
}

interface ProjectsTabProps {
  api: ApiClient;
}

export default function ProjectsTab({ api }: ProjectsTabProps) {
  const { role, setProjectId } = useAuthContext();
  const isAdmin = role === 'org_admin';

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [createMsg, setCreateMsg] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const data = await api.listProjects();
      setProjects(data as Project[]);
    } catch {
      // Failed to load
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadProjects(); }, [api]);

  const handleCreate = async () => {
    if (!newName.trim() || !newSlug.trim()) {
      setCreateMsg('Name and slug are required');
      return;
    }
    try {
      const p = await api.createProject(newName.trim(), newSlug.trim(), newDesc.trim());
      setCreateMsg(`Created: ${(p as Project).name}`);
      setNewName('');
      setNewSlug('');
      setNewDesc('');
      setShowCreate(false);
      loadProjects();
    } catch (e: unknown) {
      setCreateMsg(e instanceof Error ? e.message : 'Failed to create project');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-mid text-sm">Loading projects...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">Projects</h2>
          <p className="text-[0.8125rem] text-mid font-light">
            Manage your document extraction projects.
          </p>
        </div>
        {isAdmin && !showCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 text-xs font-medium bg-coral text-white rounded-md
                       hover:bg-coral-muted active:translate-y-px transition-all"
          >
            Create Project
          </button>
        )}
      </div>

      {/* Create project form */}
      {showCreate && isAdmin && (
        <div className="bg-surface border border-border-strong rounded-lg p-5 mb-6">
          <h3 className="text-sm font-medium text-cloud mb-3">Create Project</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value);
                  setNewSlug(e.target.value.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, ''));
                }}
                placeholder="e.g. Accounting"
                className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver
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
                className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver
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
            className="w-full px-3 py-2 text-sm bg-deep border border-border-strong rounded-md text-silver mb-3
                       outline-none focus:border-coral transition-colors"
          />
          <div className="flex gap-2 items-center">
            <button
              onClick={handleCreate}
              className="px-5 py-2 text-sm font-medium bg-coral text-white rounded-md
                         hover:bg-coral-muted active:translate-y-px transition-all"
            >
              Create Project
            </button>
            <button
              onClick={() => { setShowCreate(false); setCreateMsg(''); }}
              className="px-4 py-2 text-sm font-medium bg-transparent border border-border-strong text-mid rounded-md
                         hover:bg-white/[0.04] transition-colors"
            >
              Cancel
            </button>
            {createMsg && <span className="text-xs text-sage">{createMsg}</span>}
          </div>
        </div>
      )}

      {/* Project cards */}
      {projects.length === 0 ? (
        <div className="bg-surface border border-border-strong rounded-lg p-8 text-center">
          <p className="text-[0.8125rem] text-mid mb-2">No projects yet.</p>
          {isAdmin && (
            <p className="text-[0.8125rem] text-mid">
              Click "Create Project" above to get started.
            </p>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {projects.map(project => (
            <div
              key={project.id}
              className="bg-surface border border-border rounded-lg p-5 hover:border-coral/30 transition-colors cursor-pointer group"
              onClick={() => setProjectId(project.id)}
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="text-sm font-medium text-cloud group-hover:text-coral transition-colors">
                    {project.name}
                  </h3>
                  <p className="text-[0.6875rem] text-mid font-mono mt-0.5">{project.slug}</p>
                </div>
                {project.is_optimized ? (
                  <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">
                    optimized
                  </span>
                ) : (
                  <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-white/[0.04] text-mid">
                    active
                  </span>
                )}
              </div>

              {project.description && (
                <p className="text-[0.8125rem] text-mid font-light mb-3 line-clamp-2">
                  {project.description}
                </p>
              )}

              <div className="flex items-center gap-4 text-[0.6875rem] text-mid">
                <span>
                  {project.member_count} member{project.member_count !== 1 ? 's' : ''}
                </span>
                {project.created_at && (
                  <span>
                    Created {new Date(project.created_at).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
