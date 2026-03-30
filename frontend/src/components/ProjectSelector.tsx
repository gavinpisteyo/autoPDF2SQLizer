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

  useEffect(() => {
    setLoading(true);
    api.listProjects()
      .then((data: ProjectInfo[]) => setProjects(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [api]);

  const handleCreate = () => {
    if (!newName.trim()) return;
    onCreateNew(newName.trim());
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

      <div className="space-y-2 mb-5">
        {projects.map((project) => (
          <button
            key={project.id}
            onClick={() => onProjectSelected(project)}
            className="w-full text-left p-4 bg-surface border border-border rounded-lg
                       hover:border-coral/30 transition-colors group"
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
        ))}

        {/* Create New Project option */}
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full text-left p-4 bg-surface border border-dashed border-border-strong rounded-lg
                       hover:border-coral/30 transition-colors group"
          >
            <h3 className="text-sm font-medium text-coral">
              + Create New Project
            </h3>
            <p className="text-xs text-mid mt-0.5">
              Define a new document type and start extracting.
            </p>
          </button>
        ) : (
          <div className="bg-surface border border-border-strong rounded-lg p-5">
            <label className="block text-xs font-medium text-mid uppercase tracking-wide mb-1.5">
              Project Name
            </label>
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
