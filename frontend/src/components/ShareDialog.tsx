"use client";

/**
 * Create an anonymous share link for one recorded resource (recording,
 * observation frame, or event). Two-step dialog: pick expiry + optional
 * view cap, then show the link exactly once (only its hash is stored
 * server-side, so it can never be re-displayed).
 */

import { useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { formatDateTime } from "@/lib/time";

export type ShareKind = "recording" | "observation" | "event";

const KIND_NOUN: Record<ShareKind, string> = {
  recording: "recording",
  observation: "frame",
  event: "event",
};

// The API stores whole days only (clamped 1-30), so 24 hours is the
// shortest link we can offer.
const EXPIRY_OPTIONS = [
  { label: "24 hours", days: 1 },
  { label: "3 days", days: 3 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
] as const;

interface CreatedShare {
  url: string;
  expires_at: string | null;
  max_views: number | null;
}

interface ShareDialogProps {
  kind: ShareKind;
  resourceId: string;
  /** Human context ("Front door, Jun 3, 2:30 PM"). Stored as the share's
   * label so the Settings manage list stays readable. */
  label?: string;
  onClose: () => void;
}

export function ShareDialog({ kind, resourceId, label, onClose }: ShareDialogProps) {
  const { authFetch } = useAuth();
  const [expiryDays, setExpiryDays] = useState<number>(7);
  const [maxViewsInput, setMaxViewsInput] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedShare | null>(null);
  const [copied, setCopied] = useState(false);
  const linkRef = useRef<HTMLInputElement | null>(null);

  useEscapeKey(onClose);

  const noun = KIND_NOUN[kind];

  const createShare = async () => {
    setCreating(true);
    setError(null);
    try {
      const maxViews = maxViewsInput.trim() ? Math.max(1, parseInt(maxViewsInput, 10) || 1) : null;
      const res = await authFetch("/api/shares", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          resource_id: resourceId,
          expires_in_days: expiryDays,
          max_views: maxViews,
          label: label || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const detail = body && typeof body.detail === "string" ? body.detail : null;
        throw new Error(detail || `Could not create the link (${res.status})`);
      }
      const data = await res.json();
      // Prefer the server's absolute URL (public_base_url); fall back to
      // this origin + the relative path when the server has no base set.
      const url =
        typeof data.url === "string" && /^https?:\/\//.test(data.url)
          ? data.url
          : `${window.location.origin}${data.path}`;
      setCreated({ url, expires_at: data.expires_at, max_views: data.max_views });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the link");
    } finally {
      setCreating(false);
    }
  };

  const copyLink = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (http origin etc.): select the text so a manual
      // Cmd+C still works.
      linkRef.current?.select();
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-lg p-6 w-full max-w-md shadow-xl mx-4">
        <div className="flex items-start justify-between gap-4 mb-1">
          <h2 className="text-lg font-semibold">Share this {noun}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 p-1.5 -mr-1.5 -mt-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        {label && (
          <p className="text-xs text-muted-foreground mb-4 truncate">{label}</p>
        )}

        {!created ? (
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1.5">
                Link expires after
              </label>
              <div className="flex items-center gap-1.5">
                {EXPIRY_OPTIONS.map((opt) => (
                  <button
                    key={opt.days}
                    type="button"
                    onClick={() => setExpiryDays(opt.days)}
                    aria-pressed={expiryDays === opt.days}
                    className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                      expiryDays === opt.days
                        ? "border-accent bg-accent/15 text-accent"
                        : "border-border text-muted-foreground hover:text-foreground hover:bg-muted"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1.5">
                Max views (optional)
              </label>
              <input
                type="number"
                min={1}
                value={maxViewsInput}
                onChange={(e) => setMaxViewsInput(e.target.value)}
                placeholder="Unlimited"
                className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
              />
              <p className="text-[10px] text-muted-foreground mt-1">
                The link stops working after this many opens.
              </p>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed rounded-md border border-border-subtle bg-background/40 px-3 py-2">
              Anyone with the link can view this {noun} until it expires, without
              signing in. You can revoke it at any time from Settings.
            </p>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={createShare}
                disabled={creating}
                className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {creating ? "Creating." : "Create link"}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <input
                ref={linkRef}
                readOnly
                value={created.url}
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-0 px-3 py-2 rounded-md bg-background border border-border text-xs font-mono text-foreground select-all focus:outline-none focus:border-accent"
              />
              <button
                onClick={copyLink}
                className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-2 text-xs rounded-md border transition-colors ${
                  copied
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-accent bg-accent/10 text-accent hover:bg-accent/20"
                }`}
              >
                {copied ? (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    Copied
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="9" y="9" width="13" height="13" rx="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    Copy
                  </>
                )}
              </button>
            </div>

            <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 space-y-1">
              <p className="text-[11px] text-warning/90 leading-relaxed">
                Anyone with this link can view the {noun}
                {created.expires_at ? (
                  <> until <span className="font-mono">{formatDateTime(created.expires_at)}</span></>
                ) : (
                  " until it expires"
                )}
                {created.max_views != null &&
                  ` (or after ${created.max_views} view${created.max_views === 1 ? "" : "s"})`}
                . No sign-in required.
              </p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                This link is shown only once. Copy it now; you can revoke it later
                from Settings, but not view it again.
              </p>
            </div>

            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
