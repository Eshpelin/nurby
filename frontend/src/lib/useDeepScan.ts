"use client";

// Drives a FindAnything deep visual scan: POST /api/search/scan to start, then
// poll GET /api/search/scan/{id} until it finishes, streaming partial
// frames-with-boxes back as the GPU grounds each candidate. The button that
// calls start() IS the cost consent (design §3.6), so there is no separate
// confirm step here.

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

export interface ScanBox {
  bbox_norm: [number, number, number, number]; // x1,y1,x2,y2 in [0,1]
  is_point: boolean;
  label: string;
}

export interface ScanFrame {
  observation_id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  thumbnail_path: string | null;
  boxes: ScanBox[];
}

export interface ScanRouted {
  kind: string;
  name: string;
  message: string;
}

export interface ScanStatus {
  scan_id: string;
  status: "running" | "done" | "error";
  scanned: number;
  total: number;
  found: number;
  summary: string;
  results: ScanFrame[];
  routed: ScanRouted | null;
  error: string | null;
  leaves_privacy_boundary: boolean;
}

export interface UseDeepScan {
  scan: ScanStatus | null;
  error: string | null;
  running: boolean;
  start: (query: string, opts?: { camera_id?: string; max_frames?: number }) => Promise<void>;
  reset: () => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function useDeepScan(): UseDeepScan {
  const { authFetch } = useAuth();
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A monotonically increasing run token. Bumping it abandons any in-flight
  // poll loop (the loop checks it stayed current), so a new scan, a reset, or
  // an unmount cleanly supersedes the previous one without dangling timers.
  const runIdRef = useRef(0);

  const reset = useCallback(() => {
    runIdRef.current += 1;
    setScan(null);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      runIdRef.current += 1;
    };
  }, []);

  const start = useCallback(
    async (query: string, opts?: { camera_id?: string; max_frames?: number }) => {
      const myRun = ++runIdRef.current;
      const alive = () => runIdRef.current === myRun;
      setError(null);
      setScan(null);
      const q = (query || "").trim();
      if (!q) return;

      let data: ScanStatus;
      try {
        const res = await authFetch("/api/search/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, ...opts }),
        });
        if (!alive()) return;
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setError(body?.detail ?? `Scan failed (${res.status}).`);
          return;
        }
        data = (await res.json()) as ScanStatus;
        setScan(data);
      } catch (e) {
        if (alive()) setError(e instanceof Error ? e.message : "Network error.");
        return;
      }

      while (alive() && data.status === "running") {
        await sleep(1200);
        if (!alive()) return;
        try {
          const res = await authFetch(`/api/search/scan/${data.scan_id}`);
          if (!alive()) return;
          if (!res.ok) {
            setError(`Scan poll failed (${res.status}).`);
            return;
          }
          data = (await res.json()) as ScanStatus;
          setScan(data);
        } catch (e) {
          if (alive()) setError(e instanceof Error ? e.message : "Scan poll error.");
          return;
        }
      }
    },
    [authFetch],
  );

  return { scan, error, running: scan?.status === "running", start, reset };
}
