"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useWSSubscribe } from "@/lib/ws";
import { formatDateTime, formatWith } from "@/lib/time";

interface Visitor {
  name: string;
  sightings: number;
  first_seen?: string | null;
  last_seen?: string | null;
  cameras?: string[];
}

interface Facts {
  visitors?: Visitor[];
  unknown_visitors?: number;
  incidents_count?: number;
  journeys_count?: number;
  conversations_count?: number;
  packages?: number;
  vehicles?: number;
  audio_events?: Record<string, number>;
  audio_event_samples?: Record<string, string[]>;
  cameras_active?: { id: string; name: string; observations: number }[];
  notable_events?: { when?: string; text: string }[];
  notable_count?: number;
}

interface DailyDigest {
  id: string;
  window_start: string;
  window_end: string;
  generated_at: string;
  provider_name: string | null;
  summary_text: string | null;
  facts: Facts | null;
}

/**
 * Top-of-dashboard daily digest. Renders the last household-wide
 * morning summary from /api/daily-digest plus a structured bullet
 * list from the ``facts`` dict so the UI works even when the LLM
 * call returned empty.
 *
 * Updates live via the ``daily_digest_ready`` WS event so a manual
 * regen or the next scheduled run shows up without a refresh.
 */

const BRIEF_COLLAPSED_KEY = "nurby.morningBrief.collapsed";
// Shown before "show more". Enough to be useful at a glance without pushing
// the camera wall off screen.
const PREVIEW_BULLETS = 3;

export function DailyDigestCard() {
  const { authFetch } = useAuth();
  const [digest, setDigest] = useState<DailyDigest | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // The brief sits above everything else on the dashboard, so it defaults to a
  // condensed form (a couple of lines + the top few events) and remembers being
  // collapsed. Otherwise it pushed the camera wall below the fold on every load.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(BRIEF_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [showAll, setShowAll] = useState(false);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((v) => {
      const next = !v;
      try {
        window.localStorage.setItem(BRIEF_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* private mode: this session only */
      }
      return next;
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const res = await authFetch("/api/daily-digest");
      if (res.ok) {
        const data = await res.json();
        setDigest(data || null);
      }
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useWSSubscribe("daily_digest_ready", () => {
    refresh();
  });

  const runNow = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await authFetch("/api/daily-digest/run", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setDigest(data || null);
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;
  // No brief yet. show nothing rather than a placeholder. The morning brief
  // is configured in Settings → Morning digest (on by default at 7am), and
  // a real brief replaces this empty render once the scheduler runs or a
  // user generates one from Settings. Keeps the dashboard clean when empty.
  if (!digest) return null;

  const f = digest.facts || {};
  const bullets = buildBullets(f);
  const start = new Date(digest.window_start);
  const end = new Date(digest.window_end);

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      <button
        type="button"
        onClick={toggleCollapsed}
        className="w-full px-3 py-1.5 flex items-center gap-2 text-left"
      >
        <SunIcon className="w-4 h-4 text-amber-400" />
        <span className="text-xs font-medium uppercase tracking-wider text-amber-300">
          Morning brief
        </span>
        <span className="text-[10px] text-muted-foreground font-mono">
          {formatWith(start, { year: "numeric", month: "numeric", day: "numeric" })} {formatWith(start, {hour:"2-digit",minute:"2-digit"})} → {formatWith(end, { year: "numeric", month: "numeric", day: "numeric" }) !== formatWith(start, { year: "numeric", month: "numeric", day: "numeric" }) ? `${formatWith(end, { year: "numeric", month: "numeric", day: "numeric" })} ` : ""}{formatWith(end, {hour:"2-digit",minute:"2-digit"})}
        </span>
        <ChevronIcon
          className={`ml-auto w-3.5 h-3.5 text-muted-foreground transition-transform ${
            collapsed ? "-rotate-90" : ""
          }`}
        />
      </button>
      {!collapsed && (
        <div className="px-3 pb-2 space-y-1.5">
          {digest.summary_text && (
            <p
              className={`text-sm leading-relaxed text-foreground whitespace-pre-line ${
                showAll ? "" : "line-clamp-2"
              }`}
            >
              {digest.summary_text}
            </p>
          )}
          {bullets.length > 0 && (
            <ul className="text-xs space-y-0.5">
              {(showAll ? bullets : bullets.slice(0, PREVIEW_BULLETS)).map((b, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-amber-400/60 mt-1 flex-shrink-0">•</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          )}
          {(bullets.length > PREVIEW_BULLETS || (digest.summary_text?.length ?? 0) > 160) && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="text-[11px] text-amber-300/90 hover:text-amber-200"
            >
              {showAll
                ? "Show less"
                : bullets.length > PREVIEW_BULLETS
                  ? `Show ${bullets.length - PREVIEW_BULLETS} more`
                  : "Show more"}
            </button>
          )}
          {/* Provenance and the regenerate control are only worth the row once
              you have chosen to read the whole thing. */}
          {showAll && (
          <div className="flex items-center gap-2 pt-1 text-[10px] text-muted-foreground/70">
            <span>
              {digest.provider_name
                ? `narrated by ${digest.provider_name}`
                : "facts only (no LLM)"}
            </span>
            <span>·</span>
            <span>{formatDateTime(digest.generated_at)}</span>
            <button
              type="button"
              onClick={runNow}
              disabled={busy}
              className="ml-auto px-2 py-0.5 rounded border border-border text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {busy ? "Re-running." : "Regenerate"}
            </button>
          </div>
          )}
        </div>
      )}
    </div>
  );
}

// Supporting detail under the narrative. the actual notable events with
// friendly times, not raw counts. The story is the headline. these are the
// "what specifically" a curious user can scan. Empty on a quiet night.
function buildBullets(f: Facts): string[] {
  const events = f.notable_events || [];
  return events
    .slice(0, 8)
    .map((e) => (e.when ? `${e.when} · ${e.text}` : e.text));
}


function SunIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function ChevronIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
