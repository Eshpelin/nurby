"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AddCameraModal } from "@/components/AddCameraModal";
import { CameraSidebarCard } from "@/components/dashboard/CameraSidebarCard";
import { useAuth } from "@/lib/auth";
import type { ActivityEvent, Camera } from "@/app/dashboard-types";

/**
 * Cameras: show me (docs/ia-rollout.md).
 *
 * Web never had a cameras index; the dashboard at / was the grid. Home
 * keeps the dashboard's live wall and recap, and this page is the plain
 * list for getting to one camera's settings.
 */
type Cam = Camera & {
  content_health_enabled?: boolean;
  health_status?: "healthy" | "degraded";
  health_reason?: string | null;
};

export default function CamerasIndexPage() {
  const { authFetch } = useAuth();
  const [cams, setCams] = useState<Cam[] | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const loadCameras = useCallback(async () => {
    const res = await authFetch("/api/cameras?limit=100");
    if (res.ok) setCams(await res.json());
  }, [authFetch]);

  async function toggleHealth(camera: Cam) {
    setSaving(camera.id);
    try {
      const res = await authFetch(`/api/cameras/${camera.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_health_enabled: !camera.content_health_enabled }),
      });
      if (res.ok) {
        const updated = await res.json();
        setCams((prev) => prev?.map((c) => c.id === camera.id ? { ...c, ...updated } : c) ?? prev);
      }
    } finally {
      setSaving(null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await authFetch("/api/cameras?limit=100");
      if (!res.ok || cancelled) return;
      setCams(await res.json());
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Cameras</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Every camera, and everything about it. The live wall is on <Link href="/" className="underline">Home</Link>.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="shrink-0 rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90"
          >
            + Add camera
          </button>
        </div>
        <p className="text-xs text-muted-foreground mt-3 rounded-md border border-border bg-muted/20 px-3 py-2">
          Content health watches for frozen, obscured, or unexpectedly re-aimed views. When enabled, Nurby creates an in-app alert automatically when a problem starts and when it recovers.
        </p>
      </div>
      {cams === null ? (
        <p className="text-sm text-muted-foreground">Loading</p>
      ) : cams.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm text-muted-foreground">No cameras yet.</p>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="mt-3 rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90"
          >
            Add your first camera
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {cams.map((c) => (
              <div key={c.id} className="space-y-2">
                <CameraSidebarCard
                  camera={c}
                  selected={false}
                  onClick={() => { window.location.href = `/cameras/${c.id}`; }}
                  activityEvents={[] as ActivityEvent[]}
                  layout="single"
                />
                <div className="rounded-lg border border-border bg-card px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">Content health</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {c.content_health_enabled ? "Monitoring is active." : "Monitoring is not active."}
                      </p>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 text-xs ${c.health_status === "degraded" ? "text-red-400" : c.content_health_enabled ? "text-green-400" : "text-muted-foreground"}`}>
                      <span className={`h-2 w-2 rounded-full ${c.health_status === "degraded" ? "bg-red-400" : c.content_health_enabled ? "bg-green-400" : "bg-muted-foreground"}`} />
                      {c.health_status === "degraded" ? "Needs attention" : c.content_health_enabled ? "Healthy" : "Not monitored"}
                    </span>
                  </div>
                  {c.health_status === "degraded" && c.health_reason && (
                    <p className="mt-2 text-xs text-red-400">{c.health_reason}</p>
                  )}
                  <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
                    <span className="text-[11px] text-muted-foreground">Alerts on silent camera failures</span>
                    <button
                      type="button"
                      aria-pressed={Boolean(c.content_health_enabled)}
                      disabled={saving === c.id}
                      onClick={() => toggleHealth(c)}
                      className="text-xs text-muted-foreground underline hover:text-foreground disabled:opacity-50"
                    >
                      {saving === c.id ? "Saving…" : c.content_health_enabled ? "Disable" : "Enable"}
                    </button>
                  </div>
                  <div className="mt-3 flex gap-3 text-xs">
                    <Link href={`/cameras/${c.id}`} className="text-accent hover:underline">Camera settings →</Link>
                    <Link href={`/recordings?camera_id=${c.id}`} className="text-muted-foreground hover:text-foreground hover:underline">View recordings →</Link>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">Click a preview to open the camera workspace. Use the controls there to configure the feed, recording, audio, and analysis.</p>
        </div>
      )}
      {modalOpen && (
        <AddCameraModal
          onClose={() => setModalOpen(false)}
          onSuccess={() => {
            setModalOpen(false);
            void loadCameras();
          }}
        />
      )}
    </div>
  );
}
