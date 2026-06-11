/**
 * Relative-time formatting shared across every surface.
 *
 * One implementation instead of the nine near-identical copies that used to
 * live in individual pages and components. Buckets: just now (or seconds),
 * minutes, hours, days, months.
 */

export type TimeAgoOptions = {
  /** Shown when the timestamp is null, undefined, or empty. Default "". */
  fallback?: string;
  /** Show "42s ago" under a minute instead of "just now". Useful where
   * freshness precision matters (presence checks, test panels). */
  seconds?: boolean;
};

export function timeAgo(
  iso: string | null | undefined,
  opts: TimeAgoOptions = {}
): string {
  if (!iso) return opts.fallback ?? "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return opts.seconds ? `${s}s ago` : "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

// ── Absolute formatting ──────────────────────────────────────────────
//
// One house style for absolute dates and times, so the same moment reads
// the same on every page. Use these instead of ad-hoc `toLocaleString()`,
// which renders differently across pages and locales. All tolerate
// null/empty (return "") and an unparseable string (return it verbatim).

function _date(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? null : t;
}

/** Clock only, e.g. "2:30 PM". */
export function formatTime(iso: string | null | undefined): string {
  const d = _date(iso);
  if (!d) return iso ?? "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Calendar date, e.g. "Jun 3, 2026". Omits the year when it is the
 * current year, e.g. "Jun 3". */
export function formatDate(iso: string | null | undefined): string {
  const d = _date(iso);
  if (!d) return iso ?? "";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** Date + time, e.g. "Jun 3, 2:30 PM" (or with the year when not this
 * year). The default for any place that shows a full timestamp. */
export function formatDateTime(iso: string | null | undefined): string {
  const d = _date(iso);
  if (!d) return iso ?? "";
  return `${formatDate(iso)}, ${formatTime(iso)}`;
}
