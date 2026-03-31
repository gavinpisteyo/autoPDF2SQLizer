export const APP_VERSION = '2.0.0';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuthContext, AUTH_ENABLED } from './lib/auth';
import { createApiClient } from './lib/api';
import type { ApiClient } from './lib/api';
import TopBar from './components/TopBar';
import LoginScreen from './components/LoginScreen';
import OnboardingScreen from './components/OnboardingScreen';
import DocumentsTab from './pages/DocumentsTab';
import ChatTab from './pages/ChatTab';
import ProfilePage from './pages/ProfilePage';

type TabId = 'projects' | 'chat';

export default function App() {
  const auth = useAuthContext();
  const { isAuthenticated, isLoading, getToken, orgId, projectId, setRole } = auth;

  const [activeTab, setActiveTab] = useState<TabId>('projects');
  const [showProfile, setShowProfile] = useState(false);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [onboardingChecked, setOnboardingChecked] = useState(false);

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

  const handleGoToChat = useCallback(() => {
    setActiveTab('chat');
  }, []);

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

  // Onboarding -- user has no orgs yet
  if (AUTH_ENABLED && needsOnboarding) {
    return (
      <OnboardingScreen
        api={api}
        userName={auth.user?.name || ''}
        onOrgCreated={(newOrgId) => {
          setNeedsOnboarding(false);
          auth.switchOrg(newOrgId);
        }}
        onJoinRequested={() => {}}
      />
    );
  }

  return (
    <div className="max-w-[1000px] mx-auto px-8 pt-12 pb-16">
      <TopBar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onProfileClick={() => setShowProfile(true)}
      />

      {/* Panels */}
      {activeTab === 'projects' && (
        <DocumentsTab api={api} onGoToChat={handleGoToChat} />
      )}
      {activeTab === 'chat' && <ChatTab api={api} />}

      {/* Profile overlay */}
      {showProfile && (
        <ProfilePage api={api} onClose={() => setShowProfile(false)} />
      )}
    </div>
  );
}
