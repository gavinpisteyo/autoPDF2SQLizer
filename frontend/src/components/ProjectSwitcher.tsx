import { useEffect, useState } from 'react';
import { useAuthContext } from '../lib/auth';
import type { ApiClient } from '../lib/api';

interface Project {
  id: string;
  name: string;
  slug: string;
  member_count: number;
}

interface ProjectSwitcherProps {
  api: ApiClient;
}

export default function ProjectSwitcher({ api }: ProjectSwitcherProps) {
  const { projectId, setProjectId } = useAuthContext();
  const [projects, setProjects] = useState<Project[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => {});
  }, [api]);

  const current = projects.find(p => p.id === projectId);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium
                   bg-surface border border-border-strong rounded-md text-silver
                   hover:bg-white/[0.04] transition-colors"
      >
        <span className="w-2 h-2 rounded-full bg-coral" />
        {current ? current.name : projectId ? 'Unknown project' : 'No project'}
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 bg-surface border border-border-strong rounded-lg shadow-xl z-50 min-w-[220px] overflow-hidden">
          <div className="px-3 py-2 border-b border-border">
            <span className="text-xs text-mid">Switch Project</span>
          </div>
          {projects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-mid">No projects yet</div>
          ) : (
            projects.map(p => (
              <button
                key={p.id}
                onClick={() => { setProjectId(p.id); setOpen(false); }}
                className={`w-full text-left px-3 py-2.5 text-sm hover:bg-white/[0.04] transition-colors flex items-center justify-between ${
                  p.id === projectId ? 'text-coral' : 'text-silver'
                }`}
              >
                <span>{p.name}</span>
                {p.id === projectId && <span className="w-1.5 h-1.5 rounded-full bg-coral" />}
              </button>
            ))
          )}
          <button
            onClick={() => { setProjectId(''); setOpen(false); }}
            className="w-full text-left px-3 py-2.5 text-xs text-mid hover:bg-white/[0.04] border-t border-border transition-colors"
          >
            Org level (no project)
          </button>
        </div>
      )}
    </div>
  );
}
