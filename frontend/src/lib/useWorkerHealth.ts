"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";

interface Workers {
  ingestion: boolean;
  perception: boolean;
}

const LABELS: Record<keyof Workers, string> = {
  ingestion: "video ingestion",
  perception: "AI perception",
};

export interface DegradedComponent {
  id: string;
  label: string;
  detail: string;
}

/**
 * Which background workers are down, and which pipeline components are alive
 * but functionally broken (degraded).
 *
 * Exists because a stopped worker used to be invisible: the dashboard said
 * "Nothing happened yet" and the doctor blamed the user's stream URL and
 * credentials, while the real answer was that nothing was running. The same
 * blind spot applied one level deeper: a worker could heartbeat while its
 * pipeline silently produced nothing (a model that failed to load, a write
 * path that crashed on every row). `degraded` surfaces those.
 *
 * Returns [] while loading or unknown, so callers never flash a false
 * "not running" during the first poll.
 */
export function useWorkerHealth(): {
  down: string[];
  degraded: DegradedComponent[];
  loaded: boolean;
} {
  const { authFetch, token } = useAuth();
  const [workers, setWorkers] = useState<Workers | null>(null);
  const [degraded, setDegraded] = useState<DegradedComponent[]>([]);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/health");
      if (res.ok) {
        const data = await res.json();
        setWorkers(data?.workers ?? null);
        setDegraded(Array.isArray(data?.degraded) ? data.degraded : []);
      }
    } catch {
      /* leave the last known value; a transient poll failure is not a
         reason to claim the workers are down */
    }
  }, [authFetch]);

  useEffect(() => {
    if (!token) return;
    load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [token, load]);

  const down = useMemo(() => {
    if (!workers) return [];
    return (Object.keys(LABELS) as (keyof Workers)[])
      .filter((k) => workers[k] === false)
      .map((k) => LABELS[k]);
  }, [workers]);

  return { down, degraded, loaded: workers !== null };
}
