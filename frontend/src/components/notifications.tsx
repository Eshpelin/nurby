"use client";

import { useEffect, useRef } from "react";
import { timeAgo } from "@/lib/time";
import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

export interface NotificationItem {
  id: string;
  message: string;
  severity: string;
  rule_id: string | null;
  camera_id: string | null;
  camera_name?: string | null;
  observation_id: string | null;
  event_id?: string | null;
  read: boolean;
  created_at: string;
  delivered_at?: string | null;
  updated_at?: string | null;
}

interface NotificationsDropdownProps {
  open: boolean;
  onClose: () => void;
  notifications: NotificationItem[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  token?: string | null;
}


const SEVERITY_DOT: Record<string, string> = {
  info: "bg-green-500",
  warning: "bg-yellow-500",
  critical: "bg-red-500",
};

export function NotificationsDropdown({
  open,
  onClose,
  notifications,
  onMarkRead,
  onMarkAllRead,
  token,
}: NotificationsDropdownProps) {
  const { user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = (key: string) => translate(locale, key);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      className="absolute right-0 top-full mt-2 w-96 max-h-[28rem] overflow-y-auto rounded-lg border border-border bg-background shadow-lg z-50"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-sm font-medium">{t("notifications.title")}</span>
        <button
          onClick={onMarkAllRead}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {t("notifications.mark_all_read")}
        </button>
      </div>

      {notifications.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          {t("notifications.empty")}
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {notifications.map((n) => (
            <li
              key={n.id}
              className={`px-4 py-3 flex items-start gap-3 ${
                n.read ? "opacity-60" : ""
              }`}
            >
              <span
                className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${
                  SEVERITY_DOT[n.severity] || SEVERITY_DOT.info
                }`}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm leading-snug break-words">{n.message}</p>
                {n.camera_name && <p className="text-xs text-muted-foreground mt-0.5">{n.camera_name}</p>}
                {n.event_id && token && n.observation_id && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/api/observations/${n.observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                    alt={t("notifications.snapshot_alt")}
                    className="mt-2 h-12 w-20 rounded border border-border object-cover"
                  />
                )}
                <span className="text-xs text-muted-foreground">
                  {n.updated_at ? `${t("notifications.updated")} ${timeAgo(n.updated_at)}` : timeAgo(n.created_at)}
                </span>
                {n.event_id && (
                  <a href={`/events?alert=${encodeURIComponent(n.event_id)}`} onClick={onClose} className="block mt-1 text-xs text-accent hover:underline">
                    {t("notifications.open_alert")}
                  </a>
                )}
                {!n.event_id && (
                  <a href={`/events?review=${encodeURIComponent(n.id)}`} onClick={onClose} className="block mt-1 text-xs text-accent hover:underline">
                    {t("notifications.open_review")}
                  </a>
                )}
              </div>
              {!n.read && (
                <button
                  onClick={() => onMarkRead(n.id)}
                  className="shrink-0 text-xs text-muted-foreground hover:text-foreground transition-colors mt-0.5"
                  title={t("notifications.mark_read")}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
