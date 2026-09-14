"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * The filter row that makes Activity one place (docs/ia-rollout.md).
 *
 * Alerts and Recordings keep their own pages because they have their own
 * layouts and filters; the bar sits at the top of those too, so moving
 * between kinds feels like changing a filter rather than changing page.
 * Incidents, Journeys, Conversations and Camera recaps had no page on
 * web at all and now render inside /activity.
 */
export type ActivityKind =
  | "all"
  | "alerts"
  | "sightings"
  | "incidents"
  | "journeys"
  | "conversations"
  | "recordings"
  | "recaps";

export const ACTIVITY_KINDS: { kind: ActivityKind; label: string; href: string }[] = [
  { kind: "all", label: "All", href: "/activity" },
  { kind: "alerts", label: "Alerts", href: "/events" },
  { kind: "sightings", label: "Sightings", href: "/activity?kind=sightings" },
  { kind: "incidents", label: "Incidents", href: "/activity?kind=incidents" },
  { kind: "journeys", label: "Journeys", href: "/activity?kind=journeys" },
  { kind: "conversations", label: "Conversations", href: "/activity?kind=conversations" },
  { kind: "recordings", label: "Recordings", href: "/recordings" },
  { kind: "recaps", label: "Camera recaps", href: "/activity?kind=recaps" },
];

/** Which chip is lit for the current URL. Exported for tests. */
export function activeKind(pathname: string, kind: string | null): ActivityKind {
  if (pathname.startsWith("/events")) return "alerts";
  if (pathname.startsWith("/recordings")) return "recordings";
  const k = ACTIVITY_KINDS.find((x) => x.kind === kind);
  return k ? k.kind : "all";
}

export function ActivityFilterBar() {
  const pathname = usePathname();
  const params = useSearchParams();
  const active = activeKind(pathname, params.get("kind"));

  return (
    <nav aria-label="Activity kind" className="flex gap-1.5 overflow-x-auto pb-1 -mb-1">
      {ACTIVITY_KINDS.map(({ kind, label, href }) => {
        const on = kind === active;
        return (
          <Link
            key={kind}
            href={href}
            aria-current={on ? "page" : undefined}
            className={`shrink-0 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
              on
                ? "border-accent bg-accent text-accent-foreground"
                : "border-border text-muted-foreground hover:border-accent/60 hover:text-foreground"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
