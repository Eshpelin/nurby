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
type Cam = { id: string; name: string; status?: string; location_label?: string | null };

export default function CamerasIndexPage() {
  const { authFetch } = useAuth();
  const [cams, setCams] = useState<Cam[] | null>(null);

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
      </div>
      {cams === null ? (
        <p className="text-sm text-muted-foreground">Loading</p>
      ) : cams.length === 0 ? (
        <p className="text-sm text-muted-foreground">No cameras yet. Add one from Home.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {cams.map((c) => (
            <li key={c.id}>
              <Link
                href={`/cameras/${c.id}`}
                className="block rounded-lg border border-border bg-card px-4 py-3 hover:border-accent/60 transition-colors"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{c.name}</span>
                  <span
                    className={`h-2 w-2 rounded-full ${c.status === "online" ? "bg-accent" : "bg-destructive"}`}
                    aria-label={c.status ?? "unknown"}
                  />
                </div>
                {c.location_label && <p className="text-xs text-muted-foreground mt-1">{c.location_label}</p>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
