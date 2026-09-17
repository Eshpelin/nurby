// One source of truth for "is the system healthy right now", so the same
// verdict drives the header pill and the dashboard strip instead of the
// four scattered banners/pills we had before.

export type StatusLevel = "ok" | "warn" | "down";

export interface DegradedComponent {
  label: string;
  detail?: string | null;
}

export interface SystemStatusInput {
  workersDown: string[]; // e.g. ["video ingestion", "AI perception"]
  degraded: DegradedComponent[];
  wsStatus: string; // "connected" | "connecting" | "reconnecting" | "disconnected" | ...
  aiOffline: boolean; // configured provider unreachable
}

export interface SystemStatus {
  level: StatusLevel;
  label: string; // short, for the header pill
  detail: string; // one sentence, for the strip
  href: string; // where "Details" goes
}

// Priority: nothing recording is the most severe, then detection paused,
// then a stale live view, then a degraded sub-component. Healthy is last.
export function computeSystemStatus({ workersDown, degraded, wsStatus, aiOffline }: SystemStatusInput): SystemStatus {
  if (workersDown.length > 0) {
    const which = workersDown.join(" and ");
    return {
      level: "down",
      label: "Not recording",
      detail: `${which} ${workersDown.length > 1 ? "are" : "is"} stopped, so nothing is captured and alerts won't fire. Your cameras are fine.`,
      href: "/settings",
    };
  }
  if (aiOffline) {
    return {
      level: "warn",
      label: "AI offline",
      detail: "Detection is paused. Recording continues, but no AI checks until the model is back.",
      href: "/settings",
    };
  }
  if (wsStatus !== "connected") {
    const reconnecting = wsStatus === "reconnecting" || wsStatus === "connecting";
    return {
      level: reconnecting ? "warn" : "down",
      label: reconnecting ? "Reconnecting" : "Live paused",
      detail: reconnecting
        ? "Reconnecting to live updates. Recording is unaffected."
        : "Live updates are disconnected. Recording is unaffected; reload if this persists.",
      href: "/settings",
    };
  }
  if (degraded.length > 0) {
    const names = degraded.map((d) => d.label).join(", ");
    const first = degraded[0]?.detail;
    return {
      level: "warn",
      label: "Degraded",
      detail: `${names} ${degraded.length > 1 ? "are" : "is"} degraded, so some results may be missing.${first ? ` (${first})` : ""}`,
      href: "/settings",
    };
  }
  return { level: "ok", label: "All systems live", detail: "", href: "/settings" };
}
