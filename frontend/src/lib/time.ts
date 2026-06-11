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
