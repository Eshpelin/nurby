"use client";

import { useEffect, useRef } from "react";

export interface NotificationItem {
  id: string;
  message: string;
  severity: string;
  rule_id: string | null;
  camera_id: string | null;
  observation_id: string | null;
  read: boolean;
  created_at: string;
}

interface NotificationsDropdownProps {
  open: boolean;
  onClose: () => void;
  notifications: NotificationItem[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
}

function timeAgo(dateStr: string) {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
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
}: NotificationsDropdownProps) {
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
        <span className="text-sm font-medium">Notifications</span>
        <button
          onClick={onMarkAllRead}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Mark all read
        </button>
      </div>

      {notifications.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          No notifications yet.
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
                <span className="text-xs text-muted-foreground">
                  {timeAgo(n.created_at)}
                </span>
              </div>
              {!n.read && (
                <button
                  onClick={() => onMarkRead(n.id)}
                  className="shrink-0 text-xs text-muted-foreground hover:text-foreground transition-colors mt-0.5"
                  title="Mark as read"
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
