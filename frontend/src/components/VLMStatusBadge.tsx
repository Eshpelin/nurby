"use client";

import { useEffect, useRef, useState } from "react";
import { useWSSubscribe } from "@/lib/ws";

interface Props {
  cameraId: string;
}

interface VLMState {
  status: "idle" | "queued" | "processing" | "refining" | "slow" | "stalled" | "failed" | string;
  avg_latency?: number;
  last_latency?: number;
  reason?: string;
}

// How long a "failed" pill stays visible. The backend emits "failed" as a
// one-shot signal immediately followed by the next-frame idle/processing
// update, so we latch it here long enough for a person to read it.
const FAILED_LATCH_MS = 6000;

/**
 * Per-tile VLM status pill. Subscribes via the shared WS context for
 * vlm_status events. Rendering rules.
 *
 *   idle        -> hidden
 *   queued      -> violet "Queued"
 *   processing  -> violet "Thinking"
 *   refining    -> sky-blue "Refining"   (cascade second stage)
 *   slow        -> amber "VLM slow (12.4s)"
 *   stalled     -> amber "VLM stalled"
 *   failed      -> rose  "Couldn't analyze"  (latched ~6s, then hidden)
 */
export function VLMStatusBadge({ cameraId }: Props) {
  const [state, setState] = useState<VLMState | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Set while a "failed" pill is latched. Trailing updates are ignored until
  // the latch timer fires, so the next-frame idle does not erase the failure.
  const latchedUntil = useRef(0);

  useWSSubscribe(
    "vlm_status",
    (msg) => {
      const v = (msg as { vlm?: VLMState }).vlm || ({} as VLMState);
      if (v.status === "failed") {
        // Latch the failure so the trailing idle update that follows it
        // does not erase it before the user sees "couldn't analyze".
        if (idleTimer.current) clearTimeout(idleTimer.current);
        latchedUntil.current = Date.now() + FAILED_LATCH_MS;
        setState(v);
        idleTimer.current = setTimeout(() => {
          latchedUntil.current = 0;
          setState((s) => (s ? { ...s, status: "idle" } : s));
        }, FAILED_LATCH_MS);
        return;
      }
      // While a failure is latched, drop non-failure updates entirely. The
      // latch timer owns the transition back to idle.
      if (Date.now() < latchedUntil.current) return;
      if (idleTimer.current) clearTimeout(idleTimer.current);
      setState(v);
      if (v.status && v.status !== "idle") {
        idleTimer.current = setTimeout(
          () => setState((s) => (s ? { ...s, status: "idle" } : s)),
          30000
        );
      }
    },
    cameraId
  );

  useEffect(
    () => () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    },
    []
  );

  if (!state || state.status === "idle") return null;

  const isFailed = state.status === "failed";
  const isWarn = state.status === "slow" || state.status === "stalled";
  const isRefining = state.status === "refining";
  const colorDot = isFailed
    ? "bg-rose-400"
    : isWarn
      ? "bg-amber-400"
      : isRefining
        ? "bg-sky-400"
        : "bg-violet-400";
  const colorBorder = isFailed
    ? "border-rose-400/50"
    : isWarn
      ? "border-amber-400/50"
      : isRefining
        ? "border-sky-400/50"
        : "border-violet-400/50";
  const colorText = isFailed
    ? "text-rose-300"
    : isWarn
      ? "text-amber-300"
      : isRefining
        ? "text-sky-300"
        : "text-violet-300";
  const label = isFailed
    ? "Couldn't analyze"
    : state.status === "stalled"
      ? "AI stalled"
      : state.status === "slow"
        ? `AI slow (${state.avg_latency?.toFixed(1)}s)`
        : state.status === "queued"
          ? "Queued"
          : isRefining
            ? "Refining"
            : "Thinking";
  // Non-alarming hover detail for the failure pill.
  const title = isFailed
    ? `Couldn't analyze this camera${state.reason ? ` — ${state.reason}` : ""}. It will retry on the next frame.`
    : (state.last_latency ? `${label} · last ${state.last_latency.toFixed(1)}s` : label) +
      " — the AI is describing what this camera sees";

  return (
    <div
      role="status"
      aria-label={label}
      title={title}
      className={`flex items-center gap-1 rounded-full bg-black/60 backdrop-blur-sm px-1.5 py-0.5 border ${colorBorder}`}
    >
      <span className="relative flex h-1.5 w-1.5">
        {/* No pulsing ping on a failure: it implies active work. */}
        {!isFailed && (
          <span
            className={`absolute inline-flex h-full w-full animate-ping rounded-full ${colorDot} opacity-60`}
          />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${colorDot}`} />
      </span>
      <span className={`text-[10px] uppercase tracking-wider ${colorText}`}>
        {label}
      </span>
    </div>
  );
}
