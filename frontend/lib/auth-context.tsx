"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { auth, type User } from "./api";

// Phase 10: Firebase is loaded on demand (dynamic import) so the auth
// SDK does not ship in the first-load bundle of every route — only the
// sign-in flow itself (login page) needs it eagerly.

type Ctx = { user: User | null; loading: boolean; refresh: () => Promise<void>; logout: () => Promise<void> };
const AuthContext = createContext<Ctx>({ user: null, loading: true, refresh: async () => {}, logout: async () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      setUser((await auth.me()).user);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  const logout = useCallback(async () => {
    await auth.logout();
    const { firebaseSignOut } = await import("./firebase");
    await firebaseSignOut();
    setUser(null);
  }, []);
  const value = useMemo(() => ({ user, loading, refresh, logout }), [user, loading, refresh, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
