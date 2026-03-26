import { useAuthContext, AUTH_ENABLED } from '../lib/auth';

const ROLE_LABELS: Record<string, { label: string; desc: string }> = {
  org_admin: { label: 'Admin', desc: 'Full access — manage org, execute SQL, all features' },
  developer: { label: 'Developer', desc: 'Ground truth, evaluation, DB connections, extraction' },
  business_user: { label: 'Business User', desc: 'Upload & extract PDFs, create schemas, manage ground truth' },
  viewer: { label: 'Viewer', desc: 'Read-only access to schemas and extraction results' },
};

const ALL_ROLES = ['org_admin', 'developer', 'business_user', 'viewer'];

export default function ProfileTab() {
  const { user, orgId, role, logout, hasPermission } = useAuthContext();

  if (!AUTH_ENABLED) {
    return (
      <div>
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Profile</h2>
        <div className="bg-surface border border-border rounded-lg p-6">
          <p className="text-mid text-sm">Auth is disabled (dev mode). All permissions granted.</p>
        </div>
      </div>
    );
  }

  const roleInfo = ROLE_LABELS[role] || { label: role, desc: '' };

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
              <div className="mt-3">
                <button
                  onClick={logout}
                  className="px-4 py-1.5 text-xs font-medium bg-transparent border border-border-strong
                             text-mid rounded-md hover:bg-white/[0.04] hover:text-silver transition-colors"
                >
                  Sign Out
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="h-px bg-border my-10" />

      {/* Organization */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Organization</h2>
        <div className="bg-surface border border-border rounded-lg p-6">
          <div className="flex items-center gap-3 mb-4">
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
          <p className="text-xs text-mid leading-relaxed">
            All data (uploads, schemas, ground truth, extraction results) is scoped to this organization.
            Other organizations cannot see your data.
          </p>
        </div>
      </div>

      <div className="h-px bg-border my-10" />

      {/* Role & Permissions */}
      <div className="mb-10">
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Your Role</h2>
        <div className="bg-surface border border-border rounded-lg p-6 mb-4">
          <div className="flex items-center gap-3 mb-2">
            <span className="px-3 py-1 text-xs font-medium bg-coral/10 text-coral rounded-md">
              {roleInfo.label}
            </span>
          </div>
          <p className="text-sm text-mid">{roleInfo.desc}</p>
        </div>

        {/* Permission grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <PermRow label="View schemas & results" granted={hasPermission('schemas:read')} />
          <PermRow label="Upload & extract PDFs" granted={hasPermission('extract:run')} />
          <PermRow label="Create schemas" granted={hasPermission('schemas:write')} />
          <PermRow label="Manage ground truth" granted={hasPermission('ground_truth:write')} />
          <PermRow label="Run evaluation" granted={hasPermission('evaluate:run')} />
          <PermRow label="Test DB connections" granted={hasPermission('database:connect')} />
          <PermRow label="Execute SQL" granted={hasPermission('database:execute')} />
          <PermRow label="Manage organization" granted={hasPermission('org:admin')} />
        </div>
      </div>

      <div className="h-px bg-border my-10" />

      {/* Role Reference */}
      <div>
        <h2 className="font-heading text-sm font-semibold text-cloud tracking-tight mb-4">Role Reference</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2.5 pr-4 text-xs font-medium text-mid uppercase tracking-wide">Permission</th>
                {ALL_ROLES.map(r => (
                  <th key={r} className={`text-center py-2.5 px-3 text-xs font-medium uppercase tracking-wide ${r === role ? 'text-coral' : 'text-mid'}`}>
                    {ROLE_LABELS[r]?.label || r}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <RoleRow label="View schemas & results" perms={[true, true, true, true]} currentRole={role} />
              <RoleRow label="Upload & extract" perms={[true, true, true, false]} currentRole={role} />
              <RoleRow label="Create new schemas" perms={[true, true, true, false]} currentRole={role} />
              <RoleRow label="Edit existing schemas" perms={[true, true, false, false]} currentRole={role} />
              <RoleRow label="Manage ground truth" perms={[true, true, true, false]} currentRole={role} />
              <RoleRow label="Run evaluation" perms={[true, true, false, false]} currentRole={role} />
              <RoleRow label="Generate SQL" perms={[true, true, true, false]} currentRole={role} />
              <RoleRow label="Test DB connection" perms={[true, true, false, false]} currentRole={role} />
              <RoleRow label="Execute SQL" perms={[true, false, false, false]} currentRole={role} />
              <RoleRow label="Manage organization" perms={[true, false, false, false]} currentRole={role} />
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PermRow({ label, granted }: { label: string; granted: boolean }) {
  return (
    <div className="flex items-center gap-2.5 py-2 px-3 rounded-md bg-black/20">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${granted ? 'bg-sage' : 'bg-charcoal'}`} />
      <span className={`text-sm ${granted ? 'text-silver' : 'text-mid'}`}>{label}</span>
    </div>
  );
}

function RoleRow({ label, perms, currentRole }: { label: string; perms: boolean[]; currentRole: string }) {
  return (
    <tr className="border-b border-border">
      <td className="py-2.5 pr-4 text-silver">{label}</td>
      {ALL_ROLES.map((r, i) => (
        <td key={r} className={`text-center py-2.5 px-3 ${r === currentRole ? 'bg-white/[0.02]' : ''}`}>
          {perms[i]
            ? <span className="text-sage">Y</span>
            : <span className="text-charcoal">-</span>
          }
        </td>
      ))}
    </tr>
  );
}
