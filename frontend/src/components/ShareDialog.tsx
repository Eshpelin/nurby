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
import { translate } from "@/lib/i18n";

export type ShareKind = "recording" | "observation" | "event";

const KIND_KEY: Record<ShareKind, string> = {
  recording: "share.create_recording",
  observation: "share.create_frame",
  event: "share.create_event",
};

// The API stores whole days only (clamped 1-30), so 24 hours is the
// shortest link we can offer.
const EXPIRY_OPTIONS = [
  { key: "share.expiry_24_hours", days: 1 },
  { key: "share.expiry_3_days", days: 3 },
  { key: "share.expiry_7_days", days: 7 },
  { key: "share.expiry_30_days", days: 30 },
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
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [expiryDays, setExpiryDays] = useState<number>(7);
  const [maxViewsInput, setMaxViewsInput] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedShare | null>(null);
  const [copied, setCopied] = useState(false);
  const linkRef = useRef<HTMLInputElement | null>(null);

  useEscapeKey(onClose);

  const noun = t(KIND_KEY[kind]).replace(/^Share this |^Compartir esta /, "").toLowerCase();

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
      setError(err instanceof Error ? err.message : t("share.create_link"));
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
          <h2 className="text-lg font-semibold">{t(KIND_KEY[kind])}</h2>
          <button
            onClick={onClose}
            aria-label={t("wizard.close")}
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
                {t("share.expires_after")}
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
                    {t(opt.key)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1.5">
                {t("share.max_views")}
              </label>
              <input
                type="number"
                min={1}
                value={maxViewsInput}
                onChange={(e) => setMaxViewsInput(e.target.value)}
                placeholder={t("share.unlimited")}
                className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
              />
              <p className="text-[10px] text-muted-foreground mt-1">
                {t("share.view_limit_help")}
              </p>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed rounded-md border border-border-subtle bg-background/40 px-3 py-2">
              {t("share.anonymous_notice", { kind: noun })}
            </p>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                {t("share.cancel")}
              </button>
              <button
                onClick={createShare}
                disabled={creating}
                className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {creating ? t("share.creating") : t("share.create_link")}
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
                    {t("share.copied")}
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="9" y="9" width="13" height="13" rx="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    {t("share.copy")}
                  </>
                )}
              </button>
            </div>

            <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 space-y-1">
              <p className="text-[11px] text-warning/90 leading-relaxed">
                Anyone with this link can view the {noun}
                {created.expires_at ? (
                  <> {t("share.until")} <span className="font-mono">{formatDateTime(created.expires_at)}</span></>
                ) : (
                  ` ${t("share.until_expires")}`
                )}
                {created.max_views != null &&
                  ` (${t(created.max_views === 1 ? "share.or_after_views_one" : "share.or_after_views_other", { count: created.max_views })})`}
                {` ${t("share.no_sign_in")}`}
              </p>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {t("share.once_notice")}
              </p>
            </div>

            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                {t("share.done")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
