"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { setDisplayTimezone } from "@/lib/time";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  // Auto-created first-run owner that has not set real credentials yet.
  // Drives the "Secure your account" prompt across the app.
  is_provisional?: boolean;
  created_at: string;
  last_login_at: string | null;
}

interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  register: (
    email: string,
    password: string,
    displayName: string
  ) => Promise<void>;
  // Secure a provisional owner account (set real email + password). On
  // success the in-memory user loses its is_provisional flag.
  claimAccount: (
    email: string,
    password: string,
    displayName: string
  ) => Promise<void>;
  // Redeem an admin-issued invite key to create an account and log in.
  redeemInvite: (
    inviteKey: string,
    email: string,
    password: string,
    displayName: string
  ) => Promise<void>;
  authFetch: (url: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = "nurby_token";
const USER_KEY = "nurby_user";

const PUBLIC_PATHS = ["/login", "/setup", "/invite", "/guardian/claim"];

// /share/{token} pages are anonymous share-link viewers: never bounce a
// visitor there through login/bootstrap, and never clear their (absent)
// session on a 401.
function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.includes(pathname) || pathname.startsWith("/share/");
}

// Error that also carries the HTTP status, so callers can react to a
// 409 (duplicate / already done) without string-matching the message.
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// FastAPI returns `detail` as a string for app-level errors but as an
// array of { msg, loc } objects for 422 validation failures. Render a
// clean human string in both cases (this is what produced the
// "[object Object]" message before).
function extractDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" ? (d as { msg?: string }).msg : String(d)))
      .filter(Boolean);
    if (msgs.length) return msgs.join(". ");
  }
  return fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // authFetch reads the token through this ref instead of closing over the
  // `token` state directly. Several call sites across the app memoize their
  // fetch wrappers with an empty useCallback dependency array, freezing
  // whatever authFetch identity existed at first mount (often before login
  // resolves). A ref keeps every one of those stale closures pointed at the
  // current token instead of permanently sending unauthenticated requests.
  const tokenRef = useRef<string | null>(null);
  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_KEY);
    const savedUser = localStorage.getItem(USER_KEY);
    if (savedToken && savedUser) {
      setToken(savedToken);
      setUser(JSON.parse(savedUser));
    }
    setLoading(false);
  }, []);

  const saveAuth = useCallback((data: TokenResponse) => {
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  }, []);

  // Pin absolute timestamps to the installation's timezone rather than the
  // viewer's, so events read as house time from anywhere and match the clock
  // in backend-generated text. Cached in localStorage, so this refresh only
  // corrects drift (e.g. after the operator changes the setting).
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/system/timezone", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled) setDisplayTimezone(data?.timezone);
      } catch {
        /* keep the cached zone; falls back to the viewer's */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (loading) return;
    if (token || isPublicPath(pathname)) return;
    // No token on a protected path. A brand-new install (zero users) should
    // drop the visitor straight in. auto-create a provisional owner via
    // /auth/bootstrap and log them in, so they never hit a signup wall.
    // they secure the account later. Only an install that already has a
    // user bounces to /login.
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/auth/needs-setup");
        if (res.ok) {
          const data = await res.json();
          // Fresh install, or an unclaimed provisional install whose token
          // this browser lost. either way, (re-)adopt the owner session so
          // the visitor is never stranded at /login on their own setup.
          if (data?.needs_setup || data?.provisional_open) {
            const boot = await fetch("/api/auth/bootstrap", { method: "POST" });
            if (boot.ok) {
              const tokenData: TokenResponse = await boot.json();
              if (!cancelled) {
                saveAuth(tokenData);
                router.replace("/");
              }
              return;
            }
          }
        }
      } catch {
        /* fall through to /login on any error */
      }
      if (!cancelled) router.replace("/login");
    })();
    return () => {
      cancelled = true;
    };
  }, [loading, token, pathname, router, saveAuth]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(extractDetail(body, "Login failed"), res.status);
      }
      const data: TokenResponse = await res.json();
      saveAuth(data);
      router.replace("/");
    },
    [saveAuth, router]
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      const res = await fetch("/api/auth/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(extractDetail(body, "Setup failed"), res.status);
      }
      const data: TokenResponse = await res.json();
      saveAuth(data);
      router.replace("/");
    },
    [saveAuth, router]
  );

  const redeemInvite = useCallback(
    async (
      inviteKey: string,
      email: string,
      password: string,
      displayName: string
    ) => {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invite_key: inviteKey,
          email,
          password,
          display_name: displayName,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(
          extractDetail(body, "Could not create account"),
          res.status
        );
      }
      const data: TokenResponse = await res.json();
      saveAuth(data);
      router.replace("/");
    },
    [saveAuth, router]
  );

  const claimAccount = useCallback(
    async (email: string, password: string, displayName: string) => {
      const headers = new Headers({ "Content-Type": "application/json" });
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch("/api/auth/claim", {
        method: "POST",
        headers,
        body: JSON.stringify({ email, password, display_name: displayName }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(extractDetail(body, "Could not secure account"), res.status);
      }
      const updated: User = await res.json();
      setUser(updated);
      localStorage.setItem(USER_KEY, JSON.stringify(updated));
    },
    [token]
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    router.replace("/login");
  }, [router]);

  const authFetch = useCallback(
    async (url: string, init?: RequestInit): Promise<Response> => {
      // tokenRef is synced by an effect in this (parent) provider. On the
      // first commit after hydration/login, a child page's effect runs
      // BEFORE this parent effect, so the ref can still be null while the
      // token is already persisted. Fall back to localStorage (synchronous,
      // always current) so that first request is not sent unauthenticated.
      const currentToken =
        tokenRef.current ??
        (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null);
      const headers = new Headers(init?.headers);
      if (currentToken) {
        headers.set("Authorization", `Bearer ${currentToken}`);
      }
      const res = await fetch(url, { ...init, headers });
      // Stale or invalid token. Clear auth and let the bootstrap effect
      // re-route. sending to "/" (not "/login") means an unclaimed
      // provisional install re-adopts the owner instead of stranding the
      // visitor on a sign-in form they have no credentials for.
      if (res.status === 401 && currentToken) {
        setToken(null);
        setUser(null);
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        if (!isPublicPath(pathname)) {
          router.replace("/");
        }
      }
      return res;
    },
    [pathname, router]
  );

  const value = useMemo(
    () => ({ user, token, loading, login, logout, register, claimAccount, redeemInvite, authFetch }),
    [user, token, loading, login, logout, register, claimAccount, redeemInvite, authFetch]
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
