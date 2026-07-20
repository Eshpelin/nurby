"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import type {
  ObservationGroup,
} from "@/lib/observation-grouping";
import { RefinedBadge } from "@/components/RefinedBadge";
import { formatDateTime, formatWith } from "@/lib/time";

interface Props {
  group: ObservationGroup;
  cameraName?: string;
  // The page already knows how to render a single observation with
  // its full chip rail. The group passes one observation back to the
  // parent on demand so we don't have to clone all that markup here.
  renderObservation: (id: string) => React.ReactNode;
}

const ChevronDown = ({ className }: { className?: string }) => (
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

const RepeatIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="17 1 21 5 17 9" />
    <path d="M3 11V9a4 4 0 0 1 4-4h14" />
    <polyline points="7 23 3 19 7 15" />
    <path d="M21 13v2a4 4 0 0 1-4 4H3" />
  </svg>
);

/**
 * Rolling card that collapses N consecutive observations sharing the
 * same camera + person/object signature into one timeline entry. The
 * headline shows the count and the latest description. Click to
 * expand and see the individual occurrences as the page would have
 * rendered them without grouping.
 */
export function ObservationGroupCard({ group, cameraName, renderObservation }: Props) {
  const { token } = useAuth();
  const [expanded, setExpanded] = useState(false);

  const latest = group.latest;
  const oldestTs = new Date(
    group.observations[group.observations.length - 1].started_at
  );
  const newestTs = new Date(latest.started_at);
  const spanS = Math.max(
    0,
    Math.round((newestTs.getTime() - oldestTs.getTime()) / 1000)
  );
  const spanLabel =
    spanS < 60
      ? `${spanS}s`
      : spanS < 3600
        ? `${Math.round(spanS / 60)}m`
        : `${(spanS / 3600).toFixed(1)}h`;

  // Headline. Prefer named persons, fall back to dominant object.
  const named = latest.person_detections?.faces
    ?.map((f) => f.person_name)
    .filter((n): n is string => !!n) ?? [];
  const namedSet = Array.from(new Set(named));
  const headline =
    namedSet.length > 0
      ? namedSet.join(", ")
      : latest.person_detections?.faces?.length
        ? "Unknown person"
        : describeObjects(latest);

  return (
    <div className="rounded-lg border border-violet-700/30 bg-violet-950/15 hover:border-violet-600/50 overflow-hidden transition-colors">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-3 py-2.5"
      >
        <div className="flex items-center gap-2 text-[11px] mb-1.5">
          <RepeatIcon className="w-3.5 h-3.5 text-violet-400" />
          <span className="font-medium uppercase tracking-wider text-violet-300">
            Repeat · {group.occurrences}×
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">
            {cameraName || "Camera"}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground font-mono">
            over {spanLabel}
          </span>
          <ChevronDown
            className={`ml-auto w-3.5 h-3.5 text-muted-foreground transition-transform ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </div>
        <div className="flex gap-3">
          {latest.thumbnail_path && (
            <div className="w-20 h-14 flex-shrink-0 bg-black/50 rounded overflow-hidden">
              <img
                src={`/api/observations/${latest.id}/thumbnail${
                  token ? `?token=${token}` : ""
                }`}
                alt=""
                className="w-full h-full object-cover"
              />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium leading-snug">
              {headline}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                seen {group.occurrences} times
              </span>
            </p>
            {latest.vlm_description && (
              <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                {latest.vlm_description}
              </p>
            )}
            {latest.refined_by_provider_name && latest.primary_vlm_description && (
              <RefinedBadge
                primaryText={latest.primary_vlm_description}
                refinedText={latest.vlm_description || ""}
                refinerProviderName={latest.refined_by_provider_name}
              />
            )}
            <div className="mt-1 flex items-center gap-1 flex-wrap">
              {group.observations.slice(0, 8).map((o) => (
                <span
                  key={o.id}
                  className="text-[10px] font-mono text-violet-300/80 px-1 py-0.5 rounded bg-violet-500/10"
                  title={formatDateTime(o.started_at)}
                >
                  {formatWith(new Date(o.started_at), {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              ))}
              {group.observations.length > 8 && (
                <span className="text-[10px] text-muted-foreground">
                  +{group.observations.length - 8}
                </span>
              )}
            </div>
          </div>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-violet-700/30 bg-black/20 px-3 py-2.5 space-y-1.5">
          {group.observations.map((o) => (
            <div key={o.id}>{renderObservation(o.id)}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function describeObjects(o: ObservationGroup["latest"]): string {
  const objs = (o.object_detections?.objects || []).filter(
    (d) => d.label !== "license_plate"
  );
  if (objs.length === 0) return "Motion";
  const labels = Array.from(new Set(objs.map((d) => d.label)));
  if (labels.length === 1) return labels[0];
  if (labels.length === 2) return `${labels[0]} + ${labels[1]}`;
  return `${labels[0]} + ${labels.length - 1} more`;
}
