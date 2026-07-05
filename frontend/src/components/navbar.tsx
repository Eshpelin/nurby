"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { useWebSocket } from "@/lib/ws";
import { NotificationItem, NotificationsDropdown } from "./notifications";
import { SecureAccountModal } from "./SecureAccountModal";
import { MegaNav, MegaNavMobile } from "./MegaNav";

interface ProviderInfo {
  name: string;
  kind: string;
  active: boolean;
}

function SunIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function getInitials(name: string | null | undefined): string {
  if (!name) return "N";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

/**
 * Live WebSocket status. Stays silent while connected (the healthy case is
 * no chrome) and only surfaces a dot + label when the relay is connecting,
 * reconnecting, or down, so a paused live feed reads as paused, not broken.
 * Mirrors the AI-health badge dot pattern next to it.
 */
function LiveStatusBadge() {
  const { status } = useWebSocket();
  if (status === "connected") return null;

  const reconnecting = status === "reconnecting" || status === "connecting";
  const dot = reconnecting ? "bg-yellow-500 pulse-dot" : "bg-red-500 pulse-dot";
  const label = reconnecting ? "reconnecting…" : "live offline";
  const title = reconnecting
    ? "Live feed paused. Reconnecting to the camera relay."
    : "Live feed disconnected. No real-time updates right now.";

  return (
    <span
      title={title}
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2 text-xs ${reconnecting ? "text-yellow-500" : "text-red-400"}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      <span className="font-mono hidden md:inline">{label}</span>
    </span>
  );
}

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, authFetch} = useAuth();
  const role = user?.role ?? "viewer";
  const isGuardian = role === "guardian";

  // A guardian-role user has no business on operator surfaces. Keep them on
  // their panel. The API already denies the data; this is the UX guard.
  useEffect(() => {
    if (isGuardian && !pathname.startsWith("/guardian")) {
      router.replace("/guardian");
    }
  }, [isGuardian, pathname, router]);
  const { resolvedTheme, setTheme } = useTheme();
  const [provider, setProvider] = useState<ProviderInfo | null>(null);
  const [vlmHealth, setVlmHealth] = useState<{
    configured: boolean; reachable: boolean; name?: string | null;
    kind?: string | null; message?: string | null;
  } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [secureOpen, setSecureOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile menu on navigation and on Escape.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const fetchProvider = useCallback(async () => {
    try {
      const res = await authFetch("/api/providers");
      if (res.ok) {
        const list: ProviderInfo[] = await res.json();
        const active = list.find((p) => p.active) || null;
        setProvider(active);
      }
      // Reachability. distinguishes "configured" from "actually working".
      const h = await authFetch("/api/providers/health");
      if (h.ok) setVlmHealth(await h.json());
    } catch {
      /* silent */
    } finally {
      setLoaded(true);
    }
  }, []);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await authFetch("/api/notifications/count");
      if (res.ok) {
        const data = await res.json();
        setUnreadCount((prev) => (prev === data.unread ? prev : data.unread));
      }
    } catch {
      /* silent */
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await authFetch("/api/notifications?limit=20");
      if (res.ok) {
        const list: NotificationItem[] = await res.json();
        setNotifications(list);
      }
    } catch {
      /* silent */
    }
  }, []);

  const handleMarkRead = useCallback(
    async (id: string) => {
      try {
        await authFetch(`/api/notifications/${id}/read`, { method: "PATCH" });
        setNotifications((prev) =>
          prev.map((n) => (n.id === id ? { ...n, read: true } : n))
        );
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch {
        /* silent */
      }
    },
    []
  );

  const handleMarkAllRead = useCallback(async () => {
    try {
      await authFetch("/api/notifications/read-all", { method: "POST" });
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
    } catch {
      /* silent */
    }
  }, []);

  const closeDropdown = useCallback(() => setDropdownOpen(false), []);

  const toggleDropdown = useCallback(() => {
    setDropdownOpen((prev) => {
      const opening = !prev;
      if (opening) {
        fetchNotifications();
      }
      return opening;
    });
  }, [fetchNotifications]);

  useEffect(() => {
    // Guardians do not see the operator VLM-health badge.
    if (!isGuardian) fetchProvider();
    fetchUnreadCount();
    const providerInterval = setInterval(() => {
      if (!isGuardian) fetchProvider();
    }, 30000);
    const countInterval = setInterval(fetchUnreadCount, 15000);
    return () => {
      clearInterval(providerInterval);
      clearInterval(countInterval);
    };
  }, [fetchProvider, fetchUnreadCount, isGuardian]);

  return (
    <div className="border-b border-border bg-background sticky top-0 z-50">
      <div className="px-3 sm:px-6 h-14 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 lg:gap-8 min-w-0 flex-1">
          {/* Hamburger. Ten nav links don't fit a phone; below md they
              live in a dropdown instead of a cramped scroll strip. */}
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="md:hidden p-1.5 -ml-1 rounded-md text-muted-foreground hover:text-foreground transition-colors flex-shrink-0"
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {menuOpen ? (
                <>
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="18" y1="6" x2="6" y2="18" />
                </>
              ) : (
                <>
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="18" x2="21" y2="18" />
                </>
              )}
            </svg>
          </button>
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-7 h-7 rounded-md bg-accent flex items-center justify-center">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="black"
                strokeWidth="2.5"
              >
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z" />
              </svg>
            </div>
            <span className="font-semibold tracking-tight">Nurby</span>
            <span className="font-mono text-xs text-muted-foreground ml-2 hidden sm:inline">
              v0.1
            </span>
          </div>

          {/* Desktop: grouped mega-menu nav (operators). A guardian-role user
              only ever has the one surface, so skip the menus for them. */}
          {isGuardian ? (
            <nav className="hidden md:flex items-center gap-1">
              <Link
                href="/guardian"
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  pathname.startsWith("/guardian") ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Guardian
              </Link>
            </nav>
          ) : (
            <MegaNav />
          )}
        </div>

        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          {/* Provisional owner. The account has no real credentials yet,
              so the install is wide open to anyone who can reach it. Make
              securing it the loudest thing on the bar. */}
          {user?.is_provisional && (
            <button
              onClick={() => setSecureOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-600 hover:bg-red-500 text-white text-xs font-semibold transition-colors animate-pulse"
              title="No password is set yet. Anyone who reaches this page is an admin. Secure it now."
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              Secure account
            </button>
          )}

          {/* Live relay status. Quiet when connected; shows reconnecting /
              offline so a stale live view reads as paused, not broken. */}
          <LiveStatusBadge />

          {(() => {
            const offline = vlmHealth ? (vlmHealth.configured && !vlmHealth.reachable) : false;
            const missing = vlmHealth ? !vlmHealth.configured : !provider;
            const dot = offline ? "bg-red-500 pulse-dot" : missing ? "bg-yellow-500" : "bg-green-500 pulse-dot";
            const label = offline
              ? "AI offline"
              : missing
                ? "AI optional"
                : provider ? `${provider.kind} / ${provider.name}` : "AI ready";
            const title = vlmHealth?.message
              || (offline
                ? "The configured AI model is unreachable."
                : missing
                  ? "AI optional — set up to enable scene descriptions & Ask Nurby. Detection, recording, and alerts work without it."
                  : "AI model is reachable.");
            return (
              <Link
                href="/settings"
                title={title}
                className={`flex items-center gap-2 text-xs transition-colors ${offline ? "text-red-400 hover:text-red-300" : "text-muted-foreground hover:text-foreground"}`}
              >
                {loaded && (
                  <>
                    <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
                    <span className="font-mono hidden md:inline">{label}</span>
                  </>
                )}
              </Link>
            );
          })()}

          {/* Theme toggle */}
          <button
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Toggle theme"
          >
            {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>

          {/* Notifications */}
          <div className="relative">
            <button
              onClick={toggleDropdown}
              className="relative p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Notifications"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-red-500 text-white text-[10px] font-bold leading-none">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>
            <NotificationsDropdown
              open={dropdownOpen}
              onClose={closeDropdown}
              notifications={notifications}
              onMarkRead={handleMarkRead}
              onMarkAllRead={handleMarkAllRead}
            />
          </div>

          {/* User avatar + logout */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-xs font-medium">
              {getInitials(user?.display_name)}
            </div>
            {/* A provisional owner has random credentials it never saw, so a
                plain logout would lock it out permanently (re-bootstrap is
                blocked once a user exists). Hide logout until the account is
                secured. the red Secure-account button is the way forward. */}
            {!user?.is_provisional && (
              <button
                onClick={logout}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Logout
              </button>
            )}
          </div>
        </div>
      </div>
      {/* Mobile nav sheet. Operators get the interactive accordion mirror of
          the desktop mega-menu; a guardian only ever needs the one surface. */}
      {menuOpen && (
        isGuardian ? (
          <nav className="md:hidden border-t border-border bg-background px-3 py-3">
            <Link
              href="/guardian"
              className={`block px-3 py-2 rounded-md text-sm ${
                pathname.startsWith("/guardian") ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Guardian
            </Link>
          </nav>
        ) : (
          <MegaNavMobile open={menuOpen} onClose={() => setMenuOpen(false)} />
        )
      )}
      {secureOpen && <SecureAccountModal onClose={() => setSecureOpen(false)} />}
    </div>
  );
}
