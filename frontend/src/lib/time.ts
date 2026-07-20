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

// ── Installation timezone ────────────────────────────────────────────
//
// Timestamps are stored in UTC. They must render in the *installation's*
// timezone (where the cameras are), not the viewer's, so an event reads as
// house time even when you are looking from another country -- and so the
// clock in a backend-generated digest sentence matches the clock on the
// recording next to it.
//
// Held in a module-level variable rather than React context so the 40-odd
// formatting call sites stay plain function calls. Seeded synchronously from
// localStorage so the first paint is already correct, then refreshed from
// /api/system/timezone.

const TZ_STORAGE_KEY = "nurby.displayTimezone";

let displayTimeZone: string | undefined = (() => {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage.getItem(TZ_STORAGE_KEY) || undefined;
  } catch {
    return undefined;
  }
})();

/** Set the zone every absolute timestamp renders in. */
export function setDisplayTimezone(tz: string | null | undefined): void {
  if (!tz || tz === displayTimeZone) return;
  displayTimeZone = tz;
  try {
    window.localStorage.setItem(TZ_STORAGE_KEY, tz);
  } catch {
    /* private mode: in-memory only */
  }
}

/** The active display zone, or undefined before it has been fetched (in
 * which case formatting falls back to the viewer's own zone). */
export function getDisplayTimezone(): string | undefined {
  return displayTimeZone;
}

function tzOpts(base: Intl.DateTimeFormatOptions): Intl.DateTimeFormatOptions {
  return displayTimeZone ? { ...base, timeZone: displayTimeZone } : base;
}

// ── Absolute formatting ──────────────────────────────────────────────
//
// One house style for absolute dates and times, so the same moment reads
// the same on every page. Use these instead of ad-hoc `toLocaleString()`,
// which renders in the viewer's zone and differs across pages and locales.
// All tolerate null/empty (return "") and an unparseable string (return it
// verbatim).

type TimeInput = string | Date | null | undefined;

function _date(iso: TimeInput): Date | null {
  if (!iso) return null;
  const t = iso instanceof Date ? iso : new Date(iso);
  return Number.isNaN(t.getTime()) ? null : t;
}

function _raw(iso: TimeInput): string {
  return typeof iso === "string" ? iso : "";
}

/** Format with custom Intl options, still pinned to the installation zone.
 * For the few places needing a shape the helpers below do not cover. */
export function formatWith(
  iso: TimeInput,
  options: Intl.DateTimeFormatOptions
): string {
  const d = _date(iso);
  if (!d) return _raw(iso);
  return d.toLocaleString([], tzOpts(options));
}

/** Clock only, e.g. "2:30 PM". */
export function formatTime(iso: TimeInput): string {
  const d = _date(iso);
  if (!d) return _raw(iso);
  return d.toLocaleTimeString([], tzOpts({ hour: "numeric", minute: "2-digit" }));
}

/** Calendar date, e.g. "Jun 3, 2026". Omits the year when it is the
 * current year, e.g. "Jun 3". */
export function formatDate(iso: TimeInput): string {
  const d = _date(iso);
  if (!d) return _raw(iso);
  // Compare years *in the display zone*: near midnight the viewer's year can
  // differ from the installation's.
  const yearIn = (x: Date) =>
    x.toLocaleDateString("en-US", tzOpts({ year: "numeric" }));
  const sameYear = yearIn(d) === yearIn(new Date());
  return d.toLocaleDateString([], tzOpts({
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  }));
}

/** Date + time, e.g. "Jun 3, 2:30 PM" (or with the year when not this
 * year). The default for any place that shows a full timestamp. */
export function formatDateTime(iso: TimeInput): string {
  const d = _date(iso);
  if (!d) return _raw(iso);
  return `${formatDate(iso)}, ${formatTime(iso)}`;
}
