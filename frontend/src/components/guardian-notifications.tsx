"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

interface GNotification {
  id: string;
  message: string;
  severity: string;
  read: boolean;
  created_at: string | null;
}

function dotColor(sev: string): string {
  if (sev === "warning") return "bg-amber-500";
  if (sev === "critical" || sev === "danger") return "bg-red-500";
  return "bg-emerald-500";
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// The guardian's own notification inbox. A bell with an unread badge that opens
// a private feed scoped to their dependant, not the household.
export function GuardianNotifications() {
  const { authFetch } = useAuth();
  const [items, setItems] = useState<GNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/guardian/notifications?limit=25");
      if (!res.ok) return;
      const data = await res.json();
      setItems(data.items || []);
      setUnread(data.unread || 0);
    } catch {
      /* keep last good state */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const markRead = useCallback(
    async (id: string) => {
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
      setUnread((u) => Math.max(0, u - 1));
      try {
        await authFetch(`/api/guardian/notifications/${id}/read`, { method: "POST" });
      } catch {
        /* optimistic; reconciles on next poll */
      }
    },
    [authFetch]
  );

  const markAll = useCallback(async () => {
    const unreadItems = items.filter((n) => !n.read);
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnread(0);
    await Promise.all(
      unreadItems.map((n) =>
        authFetch(`/api/guardian/notifications/${n.id}/read`, { method: "POST" }).catch(() => {})
      )
    );
  }, [items, authFetch]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Notifications"
        className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-[hsl(0_0%_14.9%)] text-muted-foreground transition hover:text-foreground"
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-red-500 px-1 text-[11px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-lg border border-[hsl(0_0%_14.9%)] bg-[hsl(0_0%_5.5%)] shadow-xl">
          <div className="flex items-center justify-between border-b border-[hsl(0_0%_14.9%)] px-4 py-2.5">
            <span className="text-sm font-medium">Notifications</span>
            {unread > 0 && (
              <button onClick={markAll} className="text-xs text-emerald-400 hover:text-emerald-300">
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                Nothing yet. Alerts about your dependant show up here.
              </div>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => !n.read && markRead(n.id)}
                  className={`flex w-full items-start gap-3 border-b border-[hsl(0_0%_10%)] px-4 py-3 text-left transition hover:bg-[hsl(0_0%_8%)] ${
                    n.read ? "opacity-60" : ""
                  }`}
                >
                  <span className={`mt-1.5 h-2 w-2 flex-none rounded-full ${dotColor(n.severity)}`} />
                  <span className="flex-1 text-sm text-foreground">{n.message}</span>
                  <span className="flex-none whitespace-nowrap text-xs text-muted-foreground">
                    {timeAgo(n.created_at)}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
