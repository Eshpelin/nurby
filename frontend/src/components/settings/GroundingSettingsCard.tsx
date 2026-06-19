"use client";

// Settings card for FindAnything / visual grounding. Off by default. Flipping
// it on flips the grounding_enabled app flag; the ~6GB model then downloads on
// first scan (or via scripts/setup-grounding.sh). Surfaces backend choice and
// a live health line. Admin-only writes, mirroring the other settings toggles.

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

interface GroundingHealth {
  enabled: boolean;
  status?: string;
  backend?: string;
  model_loaded?: boolean;
  downloading?: boolean;
  download_pct?: number | null;
  error?: string;
}

export function GroundingSettingsCard() {
  const { authFetch, user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [enabled, setEnabled] = useState(false);
  const [backend, setBackend] = useState<"local" | "remote">("local");
  const [remoteUrl, setRemoteUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [health, setHealth] = useState<GroundingHealth | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/settings");
      if (res.ok) {
        const d = await res.json();
        if (typeof d.grounding_enabled === "boolean") setEnabled(d.grounding_enabled);
        if (d.grounding_backend === "local" || d.grounding_backend === "remote") {
          setBackend(d.grounding_backend);
        }
        if (typeof d.grounding_remote_url === "string") setRemoteUrl(d.grounding_remote_url || "");
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const loadHealth = useCallback(async () => {
    try {
      const res = await authFetch("/api/search/grounding/health");
      if (res.ok) setHealth(await res.json());
    } catch {
      /* ignore */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (enabled) loadHealth();
  }, [enabled, loadHealth]);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setSaving(true);
      try {
        await authFetch("/api/system/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } finally {
        setSaving(false);
      }
    },
    [authFetch],
  );

  const toggle = async () => {
    const next = !enabled;
    setEnabled(next);
    await patch({ grounding_enabled: next });
    if (next) loadHealth();
  };

  if (loading) return null;

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3.5 space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium mb-1">FindAnything (visual search)</div>
          <p className="text-xs text-muted-foreground">
            Describe any object in plain language and Nurby points at it in your
            footage, beyond the fixed detector classes. Uses the LocateAnything
            model. needs an NVIDIA GPU (local) or a remote endpoint, and downloads
            ~6&nbsp;GB on first use.
          </p>
        </div>
        <button
          type="button"
          disabled={!isAdmin || saving}
          onClick={toggle}
          aria-label={enabled ? "Disable FindAnything" : "Enable FindAnything"}
          className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${enabled ? "bg-accent" : "bg-muted"} ${saving || !isAdmin ? "opacity-50" : ""}`}
        >
          <span
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${enabled ? "left-[1.375rem]" : "left-0.5"}`}
          />
        </button>
      </div>

      {enabled && (
        <div className="space-y-2 border-t border-border pt-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Backend</label>
            <select
              value={backend}
              disabled={!isAdmin}
              onChange={(e) => {
                const v = e.target.value === "remote" ? "remote" : "local";
                setBackend(v);
                patch({ grounding_backend: v });
              }}
              className="text-xs bg-background border border-border rounded px-2 py-1"
            >
              <option value="local">Local GPU (recommended)</option>
              <option value="remote">Remote endpoint</option>
            </select>
          </div>

          {backend === "remote" && (
            <div className="space-y-1">
              <input
                value={remoteUrl}
                disabled={!isAdmin}
                onChange={(e) => setRemoteUrl(e.target.value)}
                onBlur={() => patch({ grounding_remote_url: remoteUrl })}
                placeholder="https://my-gpu-box:8800"
                className="w-full text-xs font-mono bg-background border border-border rounded px-2 py-1"
              />
              <p className="text-[10px] text-amber-300">
                Remote sends frames off your machine. Prefer a local GPU for privacy.
              </p>
            </div>
          )}

          {health && (
            <p className="text-[11px] text-muted-foreground">
              Status: {health.status ?? (health.model_loaded ? "ready" : "cold")}
              {health.downloading ? ` · downloading model ${health.download_pct ?? 0}%` : ""}
              {health.error ? ` · ${health.error}` : ""}
            </p>
          )}

          {!isAdmin && (
            <p className="text-[10px] text-muted-foreground">Only an admin can change these.</p>
          )}
        </div>
      )}
    </div>
  );
}
