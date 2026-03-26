import { useState } from 'react';
import { useAuthContext } from '../lib/auth';

export default function OrgSwitcher() {
  const { orgId, switchOrg } = useAuthContext();
  const [inputOrgId, setInputOrgId] = useState('');
  const [showInput, setShowInput] = useState(false);

  const handleSwitch = () => {
    if (inputOrgId.trim()) {
      switchOrg(inputOrgId.trim());
      setShowInput(false);
      setInputOrgId('');
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setShowInput(!showInput)}
        className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium
                   bg-surface border border-border-strong rounded-md text-silver
                   hover:bg-white/[0.04] transition-colors"
      >
        <span className="w-2 h-2 rounded-full bg-sage" />
        {orgId || 'No org'}
      </button>

      {showInput && (
        <div className="absolute top-full right-0 mt-2 bg-surface border border-border-strong rounded-lg p-3 shadow-xl z-50 min-w-[220px]">
          <label className="block text-xs text-mid mb-1.5">Switch Organization</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={inputOrgId}
              onChange={(e) => setInputOrgId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSwitch()}
              placeholder="org_id"
              className="flex-1 px-2 py-1.5 text-xs bg-black border border-border-strong rounded text-silver
                         outline-none focus:border-coral transition-colors"
              autoFocus
            />
            <button
              onClick={handleSwitch}
              className="px-3 py-1.5 text-xs font-medium bg-coral text-white rounded
                         hover:bg-coral-muted transition-colors"
            >
              Switch
            </button>
          </div>
          <p className="text-[0.6875rem] text-mid mt-2">
            This will redirect to Auth0 for a new org-scoped token.
          </p>
        </div>
      )}
    </div>
  );
}
