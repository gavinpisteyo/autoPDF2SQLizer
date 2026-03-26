import { useAuthContext, AUTH_ENABLED } from '../lib/auth';
import type { ApiClient } from '../lib/api';
import OrgSwitcher from './OrgSwitcher';
import ProjectSwitcher from './ProjectSwitcher';

interface TopBarProps {
  api: ApiClient;
}

export default function TopBar({ api }: TopBarProps) {
  const { user, role, logout } = useAuthContext();

  return (
    <div className="flex items-center justify-between mb-12">
      <div>
        <h1 className="font-heading text-xl font-semibold tracking-tight text-cloud">
          autoPDF2SQLizer <span className="font-normal text-coral">by Pisteyo</span>
        </h1>
        <p className="text-[0.8125rem] text-mid mt-1 font-light tracking-wide">
          Extract structured data from documents. Build accuracy. Push to your database.
        </p>
      </div>

      <div className="flex items-center gap-3">
        {AUTH_ENABLED && <OrgSwitcher />}
        <ProjectSwitcher api={api} />

        {user && (
          <div className="flex items-center gap-2.5">
            {user.picture && (
              <img src={user.picture} alt="" className="w-7 h-7 rounded-full" />
            )}
            <div className="text-right">
              <div className="text-xs font-medium text-silver">{user.name}</div>
              <div className="text-[0.6875rem] text-mid">{role}</div>
            </div>
          </div>
        )}

        {AUTH_ENABLED && (
          <button
            onClick={logout}
            className="px-3 py-1.5 text-xs font-medium bg-transparent border border-border-strong
                       text-mid rounded-md hover:bg-white/[0.04] hover:text-silver transition-colors"
          >
            Sign Out
          </button>
        )}
      </div>
    </div>
  );
}
