import { useAuthContext, AUTH_ENABLED } from '../lib/auth';
import type { ApiClient } from '../lib/api';
import OrgSwitcher from './OrgSwitcher';
import ProjectSwitcher from './ProjectSwitcher';

interface TopBarProps {
  api: ApiClient;
}

export default function TopBar({ api }: TopBarProps) {
  const { user, role, orgId, logout } = useAuthContext();

  return (
    <div className="mb-12">
      {/* Row 1: Brand + user actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold tracking-tight text-cloud">
            autoPDF2SQLizer <span className="font-normal text-coral">by Pisteyo</span>
          </h1>
          <p className="text-[0.8125rem] text-mid mt-1 font-light tracking-wide">
            Extract structured data from documents. Build accuracy. Push to your database.
          </p>
        </div>

        {user && (
          <div className="flex items-center gap-2.5 flex-shrink-0">
            {user.picture && (
              <img src={user.picture} alt="" className="w-7 h-7 rounded-full" />
            )}
            <div className="text-right">
              <div className="text-xs font-medium text-silver whitespace-nowrap">{user.name}</div>
              <div className="text-[0.6875rem] text-mid">{role}</div>
            </div>
            {AUTH_ENABLED && (
              <button
                onClick={logout}
                className="ml-1 px-3 py-1.5 text-xs font-medium bg-transparent border border-border-strong
                           text-mid rounded-md hover:bg-white/[0.04] hover:text-silver transition-colors whitespace-nowrap"
              >
                Sign Out
              </button>
            )}
          </div>
        )}
      </div>

      {/* Row 2: Context switchers (only shown when user has an org) */}
      {orgId && (
        <div className="flex items-center gap-2 mt-4 pt-4 border-t border-border">
          {AUTH_ENABLED && <OrgSwitcher />}
          <ProjectSwitcher api={api} />
        </div>
      )}
    </div>
  );
}
