"use client";

import { useCallback, useEffect, useState } from "react";

type Lifecycle = {
  id: string;
  state: "delivered" | "waiting" | "gone";
  started_at: string;
  last_present_at: string | null;
  gone_at: string | null;
  removal_kind: "picked_up_by_person" | "removed_unobserved" | null;
  absent_checks: number;
  last_observation_id: string | null;
};

type Props = { cameraId: string; authFetch: (url: string, init?: RequestInit) => Promise<Response> };

function stateCopy(item: Lifecycle) {
  if (item.state === "delivered") return "Delivered";
  if (item.state === "waiting") return "Still waiting";
  if (item.removal_kind === "picked_up_by_person") return "Picked up by a recognized person";
  return "No longer visible";
}

export function PackageLifecycleCard({ cameraId, authFetch }: Props) {
  const [items, setItems] = useState<Lifecycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await authFetch(`/api/cameras/${cameraId}/package-lifecycle`);
      if (!response.ok) throw new Error("Unable to load package history");
      const data = await response.json();
      setItems(Array.isArray(data.items) ? data.items : []);
      setError(null);
    } catch {
      setError("Package status is temporarily unavailable.");
    } finally {
      setLoading(false);
    }
  }, [authFetch, cameraId]);

  useEffect(() => { void load(); }, [load]);

  const current = items[0];
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3.5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Package activity</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Delivery status is inferred from repeated camera evidence. A disappearance is not treated as theft automatically.
          </p>
        </div>
        {current && (
          <span className={`rounded-full px-2 py-1 text-[11px] ${current.state === "gone" && current.removal_kind !== "picked_up_by_person" ? "bg-amber-500/15 text-amber-400" : "bg-emerald-500/15 text-emerald-400"}`}>
            {stateCopy(current)}
          </span>
        )}
      </div>
      {loading ? (
        <div className="mt-3 text-xs text-muted-foreground">Loading package history…</div>
      ) : error ? (
        <div className="mt-3 text-xs text-amber-400">{error}</div>
      ) : !current ? (
        <div className="mt-3 rounded-md border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">
          No package lifecycle has been detected on this camera yet. Enable package detection on a front-door camera to begin tracking delivery and removal evidence.
        </div>
      ) : (
        <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
          <div><span className="block text-[11px] uppercase tracking-wide">Started</span>{new Date(current.started_at).toLocaleString()}</div>
          <div><span className="block text-[11px] uppercase tracking-wide">Last seen</span>{current.last_present_at ? new Date(current.last_present_at).toLocaleString() : "—"}</div>
          <div><span className="block text-[11px] uppercase tracking-wide">Evidence</span>{current.last_observation_id ? "Linked camera frame" : "Pending"}</div>
        </div>
      )}
    </section>
  );
}
