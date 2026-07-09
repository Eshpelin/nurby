"use client";

/**
 * Public share viewer. Anyone with a /share/{token} link lands here; no
 * account, no auth. Resolves the token against the unauthenticated
 * /api/share/{token} endpoint (which counts the view and enforces
 * expiry / revocation / view caps) and renders the one shared resource:
 * a recording video, an observation frame, or an event summary.
 *
 * Deliberately does NOT import any authenticated helpers (useAuth,
 * authFetch): plain same-origin fetch only, so the page works with zero
 * session state.
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { formatDateTime } from "@/lib/time";

interface ShareData {
  kind: "recording" | "observation" | "event";
  label: string | null;
  expires_at: string | null;
  views_left: number | null;
  media_path: string;
  media_type: "video" | "image" | "none";
  camera_name: string | null;
  started_at: string | null;
  duration_seconds?: number | null;
  description?: string | null;
  severity?: string | null;
}

const KIND_TITLE: Record<ShareData["kind"], string> = {
  recording: "Shared recording",
  observation: "Shared frame",
  event: "Shared event",
};

function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

// Friendly copy per failure mode. The API returns 404 for an unknown
// token and 410 with a specific detail for revoked / expired / exhausted.
function errorCopy(status: number, detail: string | null): { title: string; body: string } {
  const d = (detail || "").toLowerCase();
  if (d.includes("revoked")) {
    return {
      title: "This link was revoked",
      body: "The person who shared it turned it off. Ask them for a new link if you still need it.",
    };
  }
  if (d.includes("expired")) {
    return {
      title: "This link has expired",
      body: "Share links always have an expiry. Ask the person who shared it for a fresh one.",
    };
  }
  if (d.includes("view limit")) {
    return {
      title: "This link reached its view limit",
      body: "It was set to allow a limited number of opens, and they have been used up.",
    };
  }
  if (status === 410) {
    return {
      title: "This is no longer available",
      body: detail || "The shared item has been removed.",
    };
  }
  return {
    title: "This link is not valid",
    body: "Check that the full link was copied. It may also have been deleted.",
  };
}

export default function SharePage() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<ShareData | null>(null);
  const [error, setError] = useState<{ status: number; detail: string | null } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/share/${encodeURIComponent(token)}`);
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          const detail =
            body && typeof (body as { detail?: unknown }).detail === "string"
              ? (body as { detail: string }).detail
              : null;
          if (!cancelled) setError({ status: res.status, detail });
          return;
        }
        const payload: ShareData = await res.json();
        if (!cancelled) setData(payload);
      } catch {
        if (!cancelled) setError({ status: 0, detail: "Could not reach the server. Try again in a moment." });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      {/* Minimal header: this page has no session, so no navbar. */}
      <header className="border-b border-border-subtle">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center gap-2.5">
          <span className="w-2.5 h-2.5 rounded-full bg-accent pulse-dot" />
          <span className="text-sm font-semibold tracking-tight">Nurby</span>
          <span className="text-xs text-muted-foreground">Secure share</span>
        </div>
      </header>

      <main className="flex-1 w-full max-w-3xl mx-auto px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          </div>
        ) : error ? (
          <ExpiredCard status={error.status} detail={error.detail} />
        ) : data ? (
          <ShareContent token={token} data={data} />
        ) : null}
      </main>

      <footer className="border-t border-border-subtle">
        <div className="max-w-3xl mx-auto px-6 py-4">
          <p className="text-[11px] text-muted-foreground">
            Shared from a private Nurby camera system. This link shows one item
            only and stops working when it expires or is revoked.
          </p>
        </div>
      </footer>
    </div>
  );
}

function ExpiredCard({ status, detail }: { status: number; detail: string | null }) {
  const copy = errorCopy(status, detail);
  return (
    <div className="rounded-lg border border-border bg-card px-8 py-14 text-center max-w-md mx-auto mt-10">
      <div className="w-11 h-11 rounded-full bg-muted flex items-center justify-center mx-auto mb-4">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground">
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      </div>
      <h1 className="text-base font-semibold mb-1.5">{copy.title}</h1>
      <p className="text-sm text-muted-foreground leading-relaxed">{copy.body}</p>
    </div>
  );
}

function ShareContent({ token, data }: { token: string; data: ShareData }) {
  const mediaUrl = `/api/share/${encodeURIComponent(token)}/media`;
  const duration = formatDuration(data.duration_seconds);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{KIND_TITLE[data.kind]}</h1>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-sm text-muted-foreground">
          {data.camera_name && (
            <span className="inline-flex items-center gap-1.5">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M23 7l-7 5 7 5V7z" />
                <rect x="1" y="5" width="15" height="14" rx="2" />
              </svg>
              {data.camera_name}
            </span>
          )}
          {data.started_at && (
            <span className="font-mono text-xs">{formatDateTime(data.started_at)}</span>
          )}
          {duration && <span className="font-mono text-xs">{duration}</span>}
          {data.kind === "event" && data.severity && (
            <span
              className={`px-1.5 py-0.5 text-[10px] uppercase tracking-wider rounded border ${
                data.severity === "alert"
                  ? "border-warning/40 bg-warning/10 text-warning"
                  : "border-border bg-muted text-muted-foreground"
              }`}
            >
              {data.severity}
            </span>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {data.media_type === "video" ? (
          <video controls autoPlay playsInline className="w-full max-h-[70vh] bg-black" src={mediaUrl} />
        ) : data.media_type === "image" ? (
          // Plain <img>: the media endpoint is same-origin and token-scoped.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl} alt="Shared frame" className="w-full max-h-[70vh] object-contain bg-black" />
        ) : (
          <div className="px-6 py-14 text-center text-sm text-muted-foreground">
            No image was captured for this {data.kind}.
          </div>
        )}
        {data.description && (
          <div className="px-4 py-3 border-t border-border">
            <p className="text-sm text-foreground/90 leading-relaxed">{data.description}</p>
          </div>
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        {data.expires_at && (
          <>
            This link expires <span className="font-mono">{formatDateTime(data.expires_at)}</span>.
          </>
        )}
        {data.views_left != null && (
          <> {data.views_left} view{data.views_left === 1 ? "" : "s"} remaining.</>
        )}
      </p>
    </div>
  );
}
