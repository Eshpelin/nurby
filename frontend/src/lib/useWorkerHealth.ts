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

/**
 * Which background workers are down.
 *
 * Exists because a stopped worker used to be invisible: the dashboard said
 * "Nothing happened yet" and the doctor blamed the user's stream URL and
 * credentials, while the real answer was that nothing was running. Any
 * surface that reports an absence of events needs to know the difference
 * between "quiet" and "not running".
 *
 * Returns [] while loading or unknown, so callers never flash a false
 * "not running" during the first poll.
 */
export function useWorkerHealth(): { down: string[]; loaded: boolean } {
  const { authFetch, token } = useAuth();
  const [workers, setWorkers] = useState<Workers | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/health");
      if (res.ok) {
        const data = await res.json();
        setWorkers(data?.workers ?? null);
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

  return { down, loaded: workers !== null };
}
