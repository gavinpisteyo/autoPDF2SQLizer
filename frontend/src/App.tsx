import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthContext, AUTH_ENABLED } from './lib/auth';
import { createApiClient, type ApiClient } from './lib/api';
import TopBar from './components/TopBar';
import LoginScreen from './components/LoginScreen';
import OnboardingScreen from './components/OnboardingScreen';
import ExtractTab from './pages/ExtractTab';
import GroundTruthTab from './pages/GroundTruthTab';
import EvaluateTab from './pages/EvaluateTab';
import DatabaseTab from './pages/DatabaseTab';
import SchemasTab from './pages/SchemasTab';
import ProfileTab from './pages/ProfileTab';

type TabId = 'extract' | 'ground-truth' | 'evaluate' | 'database' | 'schemas' | 'profile';

interface TabDef {
  id: TabId;
  label: string;
  minRole: 'org_admin' | 'developer' | 'business_user' | 'viewer';
}

const TABS: TabDef[] = [
  { id: 'extract', label: 'Extract', minRole: 'business_user' },
  { id: 'ground-truth', label: 'Ground Truth', minRole: 'business_user' },
  { id: 'evaluate', label: 'Evaluate', minRole: 'developer' },
  { id: 'database', label: 'Database', minRole: 'developer' },
  { id: 'schemas', label: 'Schemas', minRole: 'viewer' },
  { id: 'profile', label: 'Profile', minRole: 'viewer' },
];

export default function App() {
  const auth = useAuthContext();
  const { isAuthenticated, isLoading, getToken, orgId, projectId, roleAtLeast, user, setRole } = auth;

  const [activeTab, setActiveTab] = useState<TabId>('extract');
  const [schemas, setSchemas] = useState<Record<string, { builtin: boolean }>>({});
  const [gtRefreshKey, setGtRefreshKey] = useState(0);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [onboardingChecked, setOnboardingChecked] = useState(false);
  const [dbConfig, setDbConfig] = useState({
    dialect: 'mssql',
    tableName: '',
    schemaName: 'dbo',
    connStr: '',
    includeDdl: false,
  });

  // Create authenticated API client (orgId may be empty during onboarding)
  const api: ApiClient = useMemo(
    () => createApiClient(getToken, orgId, projectId),
    [getToken, orgId, projectId],
  );

  // Check if user has any orgs (onboarding check)
  useEffect(() => {
    if (!isAuthenticated || !AUTH_ENABLED) { setOnboardingChecked(true); return; }
    api.listMyOrgs().then((orgs: Array<{ id: string }>) => {
      if (orgs.length === 0) {
        setNeedsOnboarding(true);
      } else if (!orgId) {
        // Auto-select first org
        auth.switchOrg(orgs[0].id);
      }
      setOnboardingChecked(true);
    }).catch(() => { setOnboardingChecked(true); });
  }, [isAuthenticated]);

  // Fetch actual role from backend (metadata DB) whenever org changes
  useEffect(() => {
    if (!isAuthenticated || !orgId) return;
    api.getMe().then((me: { role: string }) => {
      if (me.role) {
        setRole(me.role as 'org_admin' | 'developer' | 'business_user' | 'viewer');
      }
    }).catch(() => {});
  }, [isAuthenticated, orgId, api, setRole]);

  const loadSchemas = useCallback(async () => {
    try {
      const data = await api.listSchemas();
      setSchemas(data);
    } catch {}
  }, [api]);

  useEffect(() => {
    if (isAuthenticated && orgId) loadSchemas();
  }, [isAuthenticated, orgId, loadSchemas]);

  // Filter tabs by role
  const visibleTabs = TABS.filter(tab => roleAtLeast(tab.minRole));

  // Ensure active tab is visible
  useEffect(() => {
    if (visibleTabs.length && !visibleTabs.find(t => t.id === activeTab)) {
      setActiveTab(visibleTabs[0].id);
    }
  }, [visibleTabs, activeTab]);

  // Loading state
  if ((AUTH_ENABLED && isLoading) || !onboardingChecked) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center">
        <p className="text-mid text-sm">Loading...</p>
      </div>
    );
  }

  // Login gate
  if (AUTH_ENABLED && !isAuthenticated) {
    return <LoginScreen />;
  }

  // Onboarding — user has no orgs yet
  if (AUTH_ENABLED && needsOnboarding) {
    return (
      <OnboardingScreen
        api={api}
        userName={user?.name || ''}
        onOrgCreated={(newOrgId) => {
          setNeedsOnboarding(false);
          auth.switchOrg(newOrgId);
        }}
        onJoinRequested={() => {}}
      />
    );
  }

  const schemaKeys = Object.keys(schemas);

  return (
    <div className="max-w-[1000px] mx-auto px-8 pt-12 pb-16">
      <TopBar api={api} />

      {/* Navigation */}
      <nav className="flex border-b border-border mb-10">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              pr-6 py-3 text-[0.8125rem] font-medium border-b-[1.5px] -mb-px transition-colors
              ${activeTab === tab.id
                ? 'text-cloud border-coral'
                : 'text-mid border-transparent hover:text-silver'
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Panels */}
      {activeTab === 'extract' && (
        <ExtractTab
          schemas={schemaKeys}
          dbConfig={dbConfig}
          api={api}
          onGroundTruthSaved={() => setGtRefreshKey(k => k + 1)}
        />
      )}
      {activeTab === 'ground-truth' && (
        <GroundTruthTab schemas={schemaKeys} refreshKey={gtRefreshKey} api={api} />
      )}
      {activeTab === 'evaluate' && <EvaluateTab api={api} />}
      {activeTab === 'database' && (
        <DatabaseTab config={dbConfig} onChange={setDbConfig} api={api} />
      )}
      {activeTab === 'schemas' && (
        <SchemasTab schemas={schemas} onSchemasChanged={loadSchemas} api={api} />
      )}
      {activeTab === 'profile' && <ProfileTab api={api} />}
    </div>
  );
}
