"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

/**
 * Cameras: show me (docs/ia-rollout.md).
 *
 * Web never had a cameras index; the dashboard at / was the grid. Home
 * keeps the dashboard's live wall and recap, and this page is the plain
 * list for getting to one camera's settings.
 */
type Cam = {
  id: string;
  name: string;
  status?: string;
  location_label?: string | null;
  content_health_enabled?: boolean;
  health_status?: "healthy" | "degraded";
  health_reason?: string | null;
};

export default function CamerasIndexPage() {
  const { authFetch } = useAuth();
  const [cams, setCams] = useState<Cam[] | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

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
        <h1 className="text-2xl font-semibold tracking-tight">Cameras</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Every camera, and everything about it. The live wall is on <Link href="/" className="underline">Home</Link>.
        </p>
        <p className="text-xs text-muted-foreground mt-3 rounded-md border border-border bg-muted/20 px-3 py-2">
          Content health watches for frozen, obscured, or unexpectedly re-aimed views. When enabled, Nurby creates an in-app alert automatically when a problem starts and when it recovers.
        </p>
      </div>
      {cams === null ? (
        <p className="text-sm text-muted-foreground">Loading</p>
      ) : cams.length === 0 ? (
        <p className="text-sm text-muted-foreground">No cameras yet. Add one from Home.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {cams.map((c) => (
            <li key={c.id}>
              <div className="rounded-lg border border-border bg-card px-4 py-3 hover:border-accent/60 transition-colors">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{c.name}</span>
                  <span className={`text-xs ${c.health_status === "degraded" ? "text-red-400" : c.status === "online" || c.status === "recording" ? "text-green-400" : "text-muted-foreground"}`}>
                    {c.health_status === "degraded" ? "View degraded" : c.status === "online" || c.status === "recording" ? "Live" : c.status ?? "Unknown"}
                  </span>
                </div>
                {c.location_label && <p className="text-xs text-muted-foreground mt-1">{c.location_label}</p>}
                {c.health_status === "degraded" && c.health_reason && (
                  <p className="text-xs text-red-400 mt-2">{c.health_reason}</p>
                )}
                <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
                  <div>
                    <p className="text-sm">Content health</p>
                    <p className="text-[11px] text-muted-foreground">Alerts on silent camera failures</p>
                  </div>
                  <button
                    type="button"
                    aria-pressed={Boolean(c.content_health_enabled)}
                    disabled={saving === c.id}
                    onClick={() => toggleHealth(c)}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors ${c.content_health_enabled ? "border-accent bg-accent/10 text-accent" : "border-border text-muted-foreground hover:text-foreground"}`}
                  >
                    {saving === c.id ? "Saving…" : c.content_health_enabled ? "On" : "Off"}
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
