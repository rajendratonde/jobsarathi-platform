import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { setAuthHooks } from '../../api/client';
import { identityApi, type MyOrganization, type PermissionsOut, type TokenOut, type UserBrief } from '../identity/api';

// Session state for the whole app. The UI shows or hides controls from
// /me/permissions; every API still authorizes on the server.

export interface Session {
  user: UserBrief;
  activeOrganizationId: string | null;
  organizations: MyOrganization[];
  passwordChangeRequired: boolean;
  permissions: Record<string, string>; // code -> scope
}

interface AuthValue {
  session: Session | null;
  loading: boolean;
  can: (permission: string) => boolean;
  signedIn: (token: TokenOut) => Promise<void>;
  switchOrganization: (organizationId: string) => Promise<void>;
  reloadPermissions: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

// A hint (not a credential) that this browser may hold a refresh cookie, so anonymous
// visitors do not make a refresh call that can only fail.
const HINT = 'js_session_hint';
const hint = {
  get: () => { try { return localStorage.getItem(HINT) === '1'; } catch { return true; } },
  set: (on: boolean) => { try { if (on) localStorage.setItem(HINT, '1'); else localStorage.removeItem(HINT); } catch { /* storage blocked */ } },
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useRef<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  const loadPermissions = useCallback(async (t: TokenOut): Promise<PermissionsOut | null> => {
    if (t.password_change_required) return null; // the server refuses everything else until changed
    return identityApi.permissions(true);
  }, []);

  const signedIn = useCallback(async (t: TokenOut) => {
    token.current = t.access_token;
    hint.set(true);
    const perms = await loadPermissions(t);
    setSession({
      user: t.user,
      activeOrganizationId: t.active_organization_id,
      organizations: t.organizations,
      passwordChangeRequired: t.password_change_required,
      permissions: perms?.permissions ?? {},
    });
  }, [loadPermissions]);

  // One refresh at a time: the refresh cookie rotates, so parallel refreshes would race.
  const pending = useRef<Promise<boolean> | null>(null);
  const refresh = useCallback((): Promise<boolean> => {
    pending.current ??= (async () => {
      try {
        await signedIn(await identityApi.refresh());
        return true;
      } catch {
        token.current = null;
        hint.set(false);
        setSession(null);
        return false;
      } finally {
        pending.current = null;
      }
    })();
    return pending.current;
  }, [signedIn]);

  useEffect(() => {
    setAuthHooks({ token: () => token.current, refresh });
    if (hint.get()) refresh().finally(() => setLoading(false)); // resume a session from the refresh cookie
    else setLoading(false);
  }, [refresh]);

  const value = useMemo<AuthValue>(() => ({
    session,
    loading,
    can: (permission) => Boolean(session?.permissions[permission]),
    signedIn,
    switchOrganization: async (organizationId) => {
      const result = await identityApi.switchOrganization(organizationId);
      token.current = result.token.access_token;
      setSession((s) => s && {
        ...s, activeOrganizationId: organizationId, organizations: result.token.organizations,
        permissions: result.permissions.permissions,
      });
    },
    reloadPermissions: async () => {
      const perms = await identityApi.permissions();
      setSession((s) => s && { ...s, permissions: perms.permissions });
    },
    signOut: async () => {
      try { await identityApi.logout(); } finally {
        token.current = null;
        hint.set(false);
        setSession(null);
      }
    },
  }), [session, loading, signedIn]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
