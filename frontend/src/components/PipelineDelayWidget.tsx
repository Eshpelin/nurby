"use client";

/**
 * Home-screen pipeline delay strip.
 *
 * A quiet one-liner that only appears when the VLM backlog is actually
 * behind, so the dashboard isn't cluttered when everything is caught up.
 * It answers the at-a-glance question "is my AI keeping up right now?"
 * and links through to /pipeline for the full per-camera breakdown.
 *
 * Shares the /api/system/pipeline-summary endpoint with the pipeline
 * page. Polls on an interval and refetches on vlm_status WS events, with
 * an in-flight guard so a burst of events collapses to one call.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useWSSubscribe } from "@/lib/ws";

interface Summary {
  health: "clear" | "catching_up" | "backlogged" | "degraded";
  total_queued: number;
  fleet_eta_seconds: number;
  sec_per_frame: number;
}

const POLL_MS = 8000;

function fmtDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "0s";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function PipelineDelayWidget() {
  const { authFetch } = useAuth();
  const [data, setData] = useState<Summary | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const res = await authFetch("/api/system/pipeline-summary");
      if (res.ok) setData(await res.json());
    } catch {
      /* transient; keep last known value */
    } finally {
      inFlight.current = false;
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  useWSSubscribe("vlm_status", () => load());

  // Stay invisible while healthy. This strip is a delay warning, not a
  // permanent status bar.
  if (!data || data.health === "clear" || data.total_queued === 0) return null;

  const degraded = data.health === "degraded";
  const tone = degraded
    ? "border-red-500/30 bg-red-500/10 text-red-400"
    : data.health === "backlogged"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
      : "border-sky-500/30 bg-sky-500/10 text-sky-400";

  return (
    <Link
      href="/pipeline"
      className={`mb-3 flex items-center gap-3 rounded-lg border px-4 py-2.5 text-sm transition-opacity hover:opacity-90 ${tone}`}
    >
      <svg
        className={`h-4 w-4 flex-shrink-0 ${degraded ? "" : "animate-spin"}`}
        viewBox="0 0 24 24"
        fill="none"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
      <span className="flex-1">
        {degraded ? (
          <>
            <span className="font-medium">Perception needs attention.</span> A
            camera has stalled or failed while {data.total_queued} frame
            {data.total_queued === 1 ? "" : "s"} wait.
          </>
        ) : (
          <>
            <span className="font-medium">AI perception is catching up.</span>{" "}
            {data.total_queued} frame{data.total_queued === 1 ? "" : "s"} queued
            {data.fleet_eta_seconds > 0 && (
              <> · ~{fmtDuration(data.fleet_eta_seconds)} to clear</>
            )}
            {data.sec_per_frame > 0 && <> · {data.sec_per_frame}s/frame</>}
          </>
        )}
      </span>
      <span className="text-xs opacity-70 flex-shrink-0">View →</span>
    </Link>
  );
}
