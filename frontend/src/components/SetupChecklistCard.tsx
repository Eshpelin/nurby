"use client";

// Durable setup checklist on the dashboard. Unlike the one-shot wizard,
// this stays until every item is done (or the user dismisses it), so a
// skipped wizard never strands a half-configured install.

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

interface ChecklistState {
  camera_added: { done: boolean; demo_only: boolean };
  provider_connected: { done: boolean };
  first_rule_active: { done: boolean };
  notifications_configured: { done: boolean; channels: string[] };
  dismissed: boolean;
}

export function SetupChecklistCard({ onAddCamera }: { onAddCamera?: () => void }) {
  const { authFetch } = useAuth();
  const router = useRouter();
  const [state, setState] = useState<ChecklistState | null>(null);
  const [hidden, setHidden] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/setup-checklist");
      if (res.ok) setState(await res.json());
    } catch {
      /* silent. card just doesn't render */
    }
  }, [authFetch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!state || state.dismissed || hidden) return null;

  const items = [
    {
      key: "camera",
      done: state.camera_added.done && !state.camera_added.demo_only,
      half: state.camera_added.demo_only,
      label: state.camera_added.demo_only
        ? "Demo camera only. Add your own camera"
        : "Add a camera",
      onClick: () => (onAddCamera ? onAddCamera() : undefined),
    },
    {
      key: "provider",
      done: state.provider_connected.done,
      half: false,
      label: "Connect an AI provider (local or cloud)",
      onClick: () => router.push("/settings"),
    },
    {
      key: "rule",
      done: state.first_rule_active.done,
      half: false,
      label: "Create your first alert rule",
      onClick: () => router.push("/rules/new?template=package-at-door"),
    },
    {
      key: "notify",
      done: state.notifications_configured.done,
      half: false,
      label: "Set up notifications (Telegram, email, or webhook)",
      onClick: () => router.push("/settings"),
    },
  ];
  const doneCount = items.filter((i) => i.done).length;
  if (doneCount === items.length) return null;

  const dismiss = async () => {
    setHidden(true);
    try {
      await authFetch("/api/system/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ setup_checklist_dismissed: true }),
      });
    } catch {
      /* localStorage-free: server flag is the source of truth; hiding
         locally for this session is enough on failure */
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold">
          Finish setting up Nurby{" "}
          <span className="text-xs font-normal text-muted-foreground">
            {doneCount}/{items.length}
          </span>
        </div>
        <button
          onClick={dismiss}
          className="text-xs text-muted-foreground hover:text-foreground"
          title="Hide this checklist. Re-enable from Settings."
        >
          Dismiss
        </button>
      </div>
      <div className="space-y-1.5">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            // Completed steps stay clickable: "done" means "you did this
            // once", not "locked forever". The camera row in particular
            // was the only add-camera entry point on the dashboard.
            onClick={item.onClick}
            title={item.done ? "Done. Click to do it again." : undefined}
            className={`w-full flex items-center gap-2.5 text-left text-xs rounded-md px-2 py-1.5 transition-colors hover:bg-muted ${
              item.done ? "text-muted-foreground" : ""
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full border flex items-center justify-center flex-shrink-0 text-[10px] ${
                item.done
                  ? "border-emerald-500 bg-emerald-500/20 text-emerald-400"
                  : item.half
                  ? "border-amber-500 bg-amber-500/15 text-amber-400"
                  : "border-border"
              }`}
            >
              {item.done ? "✓" : item.half ? "◐" : ""}
            </span>
            <span>{item.label}</span>
            {!item.done && <span className="ml-auto text-muted-foreground">→</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
