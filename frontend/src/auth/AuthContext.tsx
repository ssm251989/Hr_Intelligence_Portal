import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { authApi, setAuthToken, setUnauthorizedHandler } from "../api/client";
import type { UserRead, UserRole } from "../api/types";
import { roleAllows } from "./roles";
import { clearOfflineData } from "../pwa";

const TOKEN_STORAGE_KEY = "hr_automation_token";

interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string | null;
  role: UserRole;
}

interface AuthContextValue {
  user: UserRead | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
  can: (allowed: readonly UserRole[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!storedToken) {
      setLoading(false);
      return;
    }
    setAuthToken(storedToken);
    authApi
      .me()
      .then(setUser)
      .catch(() => {
        setAuthToken(null);
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const { access_token } = await authApi.login({ email, password });
    localStorage.setItem(TOKEN_STORAGE_KEY, access_token);
    setAuthToken(access_token);
    setUser(await authApi.me());
  };

  const register = async (payload: RegisterPayload) => {
    await authApi.register(payload);
    await login(payload.email, payload.password);
  };

  const logout = () => {
    clearOfflineData(); // Part 14: the offline copy of this user's letters/documents must not outlive the session
    setAuthToken(null);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setUser(null);
  };

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      can: (allowed) => roleAllows(user?.role, allowed),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
