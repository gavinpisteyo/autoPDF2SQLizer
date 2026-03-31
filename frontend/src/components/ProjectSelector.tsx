import { useEffect, useState } from 'react';
import type { ApiClient } from '../lib/api';
import type { ProjectInfo } from '../hooks/useDocumentWorkflow';

interface ProjectSelectorProps {
  api: ApiClient;
  onProjectSelected: (project: ProjectInfo) => void;
  onCreateNew: (name: string) => void;
}

export default function ProjectSelector({ api, onProjectSelected, onCreateNew }: ProjectSelectorProps) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<ProjectInfo | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const loadProjects = () => {
    setLoading(true);
    api.listProjects()
      .then((data: ProjectInfo[]) => setProjects(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadProjects(); }, [api]);

  const handleCreate = () => {
    if (!newName.trim()) return;
    onCreateNew(newName.trim());
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    if (deleteConfirm.trim().toLowerCase() !== deleteTarget.name.trim().toLowerCase()) {
      setDeleteError(`Type "${deleteTarget.name}" to confirm.`);
      return;
    }
    setDeleting(true);
    setDeleteError('');
    try {
      await api.deleteProject(deleteTarget.id, deleteConfirm.trim());
      setDeleteTarget(null);
      setDeleteConfirm('');
      loadProjects();
    } catch (e: unknown) {
      setDeleteError(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setDeleting(false);
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
      <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-1">
        Select a Project
      </h2>
      <p className="text-[0.8125rem] text-mid font-light mb-5">
        Pick an existing project or create a new one to get started.
      </p>

      {/* Delete confirmation modal */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-deep border border-border-strong rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <h3 className="font-heading text-sm font-semibold text-cloud mb-2">
              Delete Project
            </h3>
            <p className="text-[0.8125rem] text-mid mb-4">
              This will permanently delete <strong className="text-silver">{deleteTarget.name}</strong> and
              all its documents, schemas, and extraction data. This cannot be undone.
            </p>
            <p className="text-[0.8125rem] text-mid mb-2">
              Type <strong className="text-coral">{deleteTarget.name}</strong> to confirm:
            </p>
            <input
              type="text"
              value={deleteConfirm}
              onChange={(e) => { setDeleteConfirm(e.target.value); setDeleteError(''); }}
              onKeyDown={(e) => e.key === 'Enter' && handleDelete()}
              placeholder={deleteTarget.name}
              autoFocus
              className="w-full px-3 py-2.5 text-sm bg-surface border border-border-strong rounded-md text-silver mb-4
                         outline-none focus:border-red-400 transition-colors"
            />
            {deleteError && (
              <p className="text-[0.8125rem] text-red-400 mb-3">{deleteError}</p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setDeleteTarget(null); setDeleteConfirm(''); setDeleteError(''); }}
                className="px-4 py-2 text-sm font-medium bg-transparent border border-border-strong text-mid rounded-md
                           hover:bg-white/[0.04] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting || deleteConfirm.trim().toLowerCase() !== deleteTarget.name.trim().toLowerCase()}
                className="px-4 py-2 text-sm font-medium bg-red-500/90 text-white rounded-md
                           hover:bg-red-500 active:translate-y-px transition-all
                           disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {deleting ? 'Deleting...' : 'Delete Project'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-2 mb-5">
        {projects.map((project) => (
          <div
            key={project.id}
            className="flex items-center bg-surface border border-border rounded-lg hover:border-coral/30 transition-colors group"
          >
            <button
              onClick={() => onProjectSelected(project)}
              className="flex-1 text-left p-4"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium text-cloud group-hover:text-coral transition-colors">
                    {project.name}
                  </h3>
                  <p className="text-xs text-mid mt-0.5">
                    {project.slug}
                    {project.member_count !== undefined && (
                      <> &middot; {project.member_count} member{project.member_count !== 1 ? 's' : ''}</>
                    )}
                  </p>
                </div>
                {project.is_optimized && (
                  <span className="text-[0.6875rem] font-medium px-2 py-0.5 rounded-sm bg-sage-bg text-sage">
                    optimized
                  </span>
                )}
              </div>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setDeleteTarget(project); }}
              className="px-3 py-2 mr-2 text-mid/40 hover:text-red-400 transition-colors text-sm rounded"
              title="Delete project"
            >
              &times;
            </button>
          </div>
        ))}

        {/* Create New Project */}
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full text-left p-4 bg-surface border border-dashed border-border-strong rounded-lg
                       hover:border-coral/30 transition-colors group"
          >
            <h3 className="text-sm font-medium text-coral">+ Create New Project</h3>
            <p className="text-xs text-mid mt-0.5">Define a new document type and start extracting.</p>
          </button>
        ) : (
          <div className="bg-surface border border-border-strong rounded-lg p-5">
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">Project Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="e.g. Invoice Processing"
              autoFocus
              className="w-full px-3 py-2.5 text-sm bg-deep border border-border-strong rounded-md text-silver mb-4
                         outline-none focus:border-coral transition-colors"
            />
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                disabled={!newName.trim()}
                className="px-5 py-2.5 text-sm font-medium bg-coral text-white rounded-md
                           hover:bg-coral-muted active:translate-y-px transition-all
                           disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Continue
              </button>
              <button
                onClick={() => { setShowCreate(false); setNewName(''); }}
                className="px-4 py-2.5 text-sm font-medium bg-transparent border border-border-strong text-mid rounded-md
                           hover:bg-white/[0.04] transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
