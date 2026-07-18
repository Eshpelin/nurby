"use client";

// On-demand FindAnything: a hover-revealed magnifier on each camera tile that
// opens a modal, grounds a plain-language prompt against the camera's latest
// frame (POST /api/search/locate-now), and overlays the boxes. The "click ->
// show me the magic" surface for a single camera, right now.

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { GroundingBoxOverlay } from "@/components/search/GroundingBoxOverlay";
import type { ScanBox } from "@/lib/useDeepScan";

interface LocateNowResult {
  found: boolean;
  boxes: ScanBox[];
  observation_id: string | null;
  camera_name: string;
  thumbnail_path: string | null;
  started_at: string | null;
  summary: string;
}

const MagnifierIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);

export function FindNowButton({ cameraId, cameraName }: { cameraId: string; cameraName?: string }) {
  const { authFetch, token } = useAuth();
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocateNowResult | null>(null);
  const [error, setError] = useState("");

  const run = async () => {
    const q = prompt.trim();
    if (!q) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await authFetch("/api/search/locate-now", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: cameraId, prompt: q }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(body?.detail || "Could not run FindAnything.");
        return;
      }
      setResult(await res.json());
    } catch {
      setError("Network error.");
    } finally {
      setLoading(false);
    }
  };

  const close = () => {
    setOpen(false);
    setResult(null);
    setError("");
  };

  return (
    <>
      <button
        type="button"
        title="Find anything in this camera now"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="absolute top-1.5 right-[6.75rem] z-10 w-6 h-6 rounded-md bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/70 hover:text-white hover:bg-black/80 transition-colors opacity-0 group-hover:opacity-100"
      >
        <MagnifierIcon className="w-3 h-3" />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={close}
        >
          <div
            className="bg-background border border-border rounded-lg max-w-lg w-full p-4 space-y-3 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">
                Find in {cameraName || result?.camera_name || "camera"}
              </div>
              <button onClick={close} className="text-muted-foreground hover:text-foreground text-xs">
                Close
              </button>
            </div>

            <div className="flex gap-2">
              <input
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") run();
                }}
                placeholder='e.g. "a red backpack" or "a chicken"'
                className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
                autoFocus
              />
              <button
                onClick={run}
                disabled={loading || !prompt.trim()}
                className="px-3 py-2 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
              >
                {loading ? "Scanning…" : result ? "Again" : "Find"}
              </button>
            </div>
            <div className="text-[11px] text-muted-foreground">
              Scans this camera&apos;s latest frame with the vision model. Describe anything —
              it isn&apos;t limited to the usual detector classes.
            </div>

            {error && <div className="text-xs text-red-400">{error}</div>}

            {result && (
              <div className="space-y-2">
                {result.observation_id && token && (
                  <div className="relative w-full rounded overflow-hidden border border-border">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/observations/${result.observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                      alt="latest frame"
                      className="w-full block"
                    />
                    <GroundingBoxOverlay boxes={result.boxes} />
                  </div>
                )}
                <div className={`text-xs ${result.found ? "text-green-400" : "text-muted-foreground"}`}>
                  {result.summary}
                </div>
                {result.started_at && (
                  <div className="text-[10px] text-muted-foreground">
                    frame at {new Date(result.started_at).toLocaleString()}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default FindNowButton;
