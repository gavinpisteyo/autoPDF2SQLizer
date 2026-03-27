/**
 * Auth0 integration — provider, hooks, and org context.
 * When VITE_AUTH_ENABLED !== 'true', auth is bypassed (dev mode).
 */

import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED === 'true';
const AUTH0_DOMAIN = import.meta.env.VITE_AUTH0_DOMAIN || '';
const AUTH0_CLIENT_ID = import.meta.env.VITE_AUTH0_CLIENT_ID || '';
const AUTH0_AUDIENCE = import.meta.env.VITE_AUTH0_AUDIENCE || '';

export { AUTH_ENABLED };

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type OrgRole = 'org_admin' | 'developer' | 'business_user' | 'viewer';

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: { name: string; email: string; picture?: string; sub?: string } | null;
  orgId: string;
  projectId: string;
  role: OrgRole;
  getToken: () => Promise<string>;
  switchOrg: (orgId: string) => void;
  setProjectId: (id: string) => void;
  setRole: (role: OrgRole) => void;
  login: () => void;
  logout: () => void;
  hasPermission: (perm: string) => boolean;
  roleAtLeast: (minimum: OrgRole) => boolean;
}

const ROLE_HIERARCHY: OrgRole[] = ['org_admin', 'developer', 'business_user', 'viewer'];

function resolveRole(permissions: string[]): OrgRole {
  const s = new Set(permissions);
  if (s.has('org:admin')) return 'org_admin';
  if (s.has('evaluate:run')) return 'developer';
  if (s.has('extract:run')) return 'business_user';
  return 'viewer';
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used inside AuthProvider');
  return ctx;
}

// ---------------------------------------------------------------------------
// Dev mode mock
// ---------------------------------------------------------------------------

function DevAuthProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState(() => localStorage.getItem('active_project_id') || '');

  const value: AuthContextValue = useMemo(() => ({
    isAuthenticated: true,
    isLoading: false,
    user: { name: 'Dev User', email: 'dev@localhost', sub: 'dev|local' },
    orgId: 'default',
    projectId,
    role: 'org_admin' as OrgRole,
    getToken: async () => '',
    switchOrg: () => {},
    setProjectId: (id: string) => { setProjectId(id); localStorage.setItem('active_project_id', id); },
    setRole: () => {},
    login: () => {},
    logout: () => {},
    hasPermission: () => true,
    roleAtLeast: () => true,
  }), [projectId]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Real Auth0 provider
// ---------------------------------------------------------------------------

function Auth0InnerProvider({ children }: { children: ReactNode }) {
  const {
    isAuthenticated,
    isLoading,
    user: auth0User,
    getAccessTokenSilently,
    loginWithRedirect,
    logout: auth0Logout,
  } = useAuth0();

  const [orgId, setOrgId] = useState(() => localStorage.getItem('active_org_id') || '');
  const [projectId, setProjectIdState] = useState(() => localStorage.getItem('active_project_id') || '');
  const [permissions, setPermissions] = useState<string[]>([]);

  // Extract permissions from token when authenticated
  useEffect(() => {
    if (!isAuthenticated) return;

    getAccessTokenSilently().then((token) => {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setPermissions(payload.permissions || []);
        if (payload.org_id && !orgId) {
          setOrgId(payload.org_id);
          localStorage.setItem('active_org_id', payload.org_id);
        }
      } catch {}
    }).catch(() => {});
  }, [isAuthenticated, getAccessTokenSilently, orgId]);

  const [roleOverride, setRoleOverride] = useState<OrgRole | null>(null);
  const role = roleOverride || resolveRole(permissions);

  const setRole = useCallback((r: OrgRole) => { setRoleOverride(r); }, []);

  const getToken = useCallback(async () => {
    try {
      return await getAccessTokenSilently();
    } catch {
      return '';
    }
  }, [getAccessTokenSilently]);

  const switchOrg = useCallback((newOrgId: string) => {
    localStorage.setItem('active_org_id', newOrgId);
    localStorage.removeItem('active_project_id');
    setOrgId(newOrgId);
    setProjectIdState('');
    // No Auth0 redirect — org context is managed locally via X-Org-Id header
  }, []);

  const login = useCallback(() => {
    loginWithRedirect();
  }, [loginWithRedirect]);

  const setProjectId = useCallback((id: string) => {
    setProjectIdState(id);
    localStorage.setItem('active_project_id', id);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('active_org_id');
    localStorage.removeItem('active_project_id');
    auth0Logout({ logoutParams: { returnTo: window.location.origin } });
  }, [auth0Logout]);

  const hasPermission = useCallback((perm: string) => permissions.includes(perm), [permissions]);

  const roleAtLeast = useCallback((minimum: OrgRole) => {
    return ROLE_HIERARCHY.indexOf(role) <= ROLE_HIERARCHY.indexOf(minimum);
  }, [role]);

  const value: AuthContextValue = useMemo(() => ({
    isAuthenticated,
    isLoading,
    user: auth0User ? {
      name: auth0User.name || auth0User.email || '',
      email: auth0User.email || '',
      picture: auth0User.picture,
      sub: auth0User.sub,
    } : null,
    orgId,
    projectId,
    role,
    getToken,
    switchOrg,
    setProjectId,
    setRole,
    login,
    logout,
    hasPermission,
    roleAtLeast,
  }), [isAuthenticated, isLoading, auth0User, orgId, projectId, role, getToken, switchOrg, setProjectId, setRole, login, logout, hasPermission, roleAtLeast]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Exported provider — picks dev or real based on env
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  if (!AUTH_ENABLED) {
    return <DevAuthProvider>{children}</DevAuthProvider>;
  }

  return (
    <Auth0Provider
      domain={AUTH0_DOMAIN}
      clientId={AUTH0_CLIENT_ID}
      authorizationParams={{
        redirect_uri: window.location.origin,
        audience: AUTH0_AUDIENCE,
        scope: 'openid profile email',
      }}
    >
      <Auth0InnerProvider>{children}</Auth0InnerProvider>
    </Auth0Provider>
  );
}
