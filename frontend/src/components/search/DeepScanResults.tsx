"use client";

// Renders a FindAnything deep-scan: the honest "what was scanned" summary,
// a routed-to-people notice when the query was about a known person (§3.4),
// a privacy warning when frames left the box (remote backend, §4), and a grid
// of matched frames with grounding boxes. Each match carries a thumbs-down so
// a wrong box can be dismissed (feeds correction; design §3.2/§6).

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import type { ScanStatus } from "@/lib/useDeepScan";
import { GroundingBoxOverlay } from "./GroundingBoxOverlay";
import { formatWith } from "@/lib/time";

export function DeepScanResults({
  scan,
  error,
}: {
  scan: ScanStatus | null;
  error: string | null;
}) {
  const { token } = useAuth();
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  if (error) {
    return (
      <div className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded p-2">
        {error}
      </div>
    );
  }
  if (!scan) return null;

  const visible = scan.results.filter((r) => !hidden.has(r.observation_id));
  const dismiss = (id: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });

  return (
    <div className="space-y-3 mt-4 border-t border-border pt-4">
      <div className="flex items-center gap-2 text-xs">
        {scan.status === "running" && (
          <span className="inline-block w-3 h-3 rounded-full border-2 border-muted-foreground/40 border-t-foreground animate-spin" />
        )}
        <span className="text-muted-foreground">{scan.summary}</span>
      </div>

      {scan.routed && (
        <div className="text-xs text-sky-300 bg-sky-500/10 border border-sky-500/30 rounded p-2">
          {scan.routed.message}
        </div>
      )}

      {scan.leaves_privacy_boundary && (
        <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded p-2">
          Frames were sent to a remote grounding endpoint (off-box). Use a local
          GPU backend to keep footage on your machine.
        </div>
      )}

      {visible.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {visible.map((r) => (
            <figure
              key={r.observation_id}
              className="relative rounded-md overflow-hidden border border-border group"
            >
              {token && (
                r.started_at ? (
                  <a
                    href={`/recordings?at=${encodeURIComponent(r.started_at)}&camera=${r.camera_id}`}
                    title="Open this moment in Recordings"
                    className="block"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/observations/${r.observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                      alt={r.boxes[0]?.label || "match"}
                      className="w-full block"
                    />
                  </a>
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/api/observations/${r.observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                    alt={r.boxes[0]?.label || "match"}
                    className="w-full block"
                  />
                )
              )}
              <GroundingBoxOverlay boxes={r.boxes} />
              <button
                type="button"
                onClick={() => dismiss(r.observation_id)}
                title="Not a match"
                aria-label="Dismiss this match"
                className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white text-xs leading-none opacity-0 group-hover:opacity-100 hover:bg-black/80"
              >
                ✕
              </button>
              <figcaption className="absolute bottom-0 inset-x-0 text-[10px] bg-black/60 text-white px-1 py-0.5 truncate">
                {r.camera_name}
                {r.started_at ? ` · ${formatWith(new Date(r.started_at), { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}` : ""}
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      {scan.status === "done" && scan.found === 0 && !scan.routed && (
        <div className="text-xs text-muted-foreground">
          No matches found. Try describing it differently (color, size, or where
          it is).
        </div>
      )}
    </div>
  );
}
