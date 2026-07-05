"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { EmptyState } from "@/components/EmptyState";

// A merged activity item from GET /timeline (observation or transcript),
// already interleaved newest-first by the backend.
interface TimelineItem {
  kind: "observation" | "transcript";
  id: string;
  camera_id: string;
  started_at: string;
  ended_at: string | null;
  // observation
  vlm_description?: string | null;
  thumbnail_path?: string | null;
  object_detections?: { objects?: { label?: string }[] } | null;
  person_detections?: { faces?: { person_name?: string | null }[] } | null;
  // transcript
  text?: string | null;
}

interface Camera {
  id: string;
  name: string;
}

const OBJECT_GLYPH: Record<string, string> = {
  person: "🧍", cat: "🐈", dog: "🐕", car: "🚗", truck: "🚚",
  bus: "🚌", bicycle: "🚲", motorcycle: "🏍️", bird: "🐦",
};

const PAGE_SIZE = 60;

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date(today.getTime() - 86400000);
  const same = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (same(d, today)) return "Today";
  if (same(d, yest)) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric", year: "numeric" });
}

function clockLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Distinct object labels (person handled separately, others become chips).
function objectLabels(item: TimelineItem): string[] {
  const out: string[] = [];
  for (const o of item.object_detections?.objects ?? []) {
    if (o.label && !out.includes(o.label)) out.push(o.label);
  }
  return out;
}
function personNames(item: TimelineItem): string[] {
  const out: string[] = [];
  for (const f of item.person_detections?.faces ?? []) {
    if (f.person_name && !out.includes(f.person_name)) out.push(f.person_name);
  }
  return out;
}

export default function TimelinePage() {
  const { authFetch, token } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [cameraFilter, setCameraFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [kindFilter, setKindFilter] = useState<"all" | "observation" | "transcript">("all");
  const [jumpError, setJumpError] = useState<string | null>(null);

  const cameraNames = useMemo(() => {
    const m: Record<string, string> = {};
    for (const c of cameras) m[c.id] = c.name;
    return m;
  }, [cameras]);

  const fetchCameras = useCallback(async () => {
    try {
      const res = await authFetch("/api/cameras");
      if (res.ok) setCameras(await res.json());
    } catch {
      /* silent */
    }
  }, [authFetch]);

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      });
      if (cameraFilter) params.set("camera_id", cameraFilter);
      if (dateFrom) params.set("from", new Date(dateFrom).toISOString());
      if (dateTo) params.set("to", new Date(dateTo).toISOString());
      const res = await authFetch(`/api/timeline?${params.toString()}`);
      if (res.ok) {
        const body = await res.json();
        setItems(body.items ?? []);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [authFetch, page, cameraFilter, dateFrom, dateTo]);

  useEffect(() => { fetchCameras(); }, [fetchCameras]);
  useEffect(() => { fetchTimeline(); }, [fetchTimeline]);

  const applyPreset = (hours: number) => {
    const now = new Date();
    setDateTo(toLocalInput(now));
    setDateFrom(toLocalInput(new Date(now.getTime() - hours * 3600 * 1000)));
    setPage(0);
  };

  // Jump into the recording covering this moment: hand the coordinates to the
  // recordings player via sessionStorage, then navigate there.
  const playMoment = (item: TimelineItem) => {
    setJumpError(null);
    try {
      sessionStorage.setItem(
        "nurby_open_moment",
        JSON.stringify({ camera_id: item.camera_id, started_at: item.started_at }),
      );
    } catch {
      setJumpError("Could not open the player.");
      return;
    }
    router.push("/recordings");
  };

  const visible = useMemo(
    () => (kindFilter === "all" ? items : items.filter((i) => i.kind === kindFilter)),
    [items, kindFilter],
  );

  // Group the visible feed by day for the rail headers.
  const groups = useMemo(() => {
    const out: { day: string; items: TimelineItem[] }[] = [];
    for (const it of visible) {
      const d = dayLabel(it.started_at);
      const last = out[out.length - 1];
      if (last && last.day === d) last.items.push(it);
      else out.push({ day: d, items: [it] });
    }
    return out;
  }, [visible]);

  const hasFilters = !!cameraFilter || !!dateFrom || !!dateTo || kindFilter !== "all";
  const hasNext = items.length === PAGE_SIZE;

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Timeline</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Everything that happened, newest first. Click any moment to watch it.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <select
          value={cameraFilter}
          onChange={(e) => { setCameraFilter(e.target.value); setPage(0); }}
          className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
        >
          <option value="">All cameras</option>
          {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        <div className="flex rounded-md border border-border overflow-hidden">
          {([
            { k: "all", label: "Everything" },
            { k: "observation", label: "Sightings" },
            { k: "transcript", label: "Speech" },
          ] as const).map((o) => (
            <button
              key={o.k}
              onClick={() => setKindFilter(o.k)}
              className={`px-3 py-2 text-xs transition-colors ${
                kindFilter === o.k
                  ? "bg-accent/15 text-accent"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              }`}
            >{o.label}</button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">From</label>
          <input type="datetime-local" value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
            className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent" />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">To</label>
          <input type="datetime-local" value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
            className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent" />
        </div>

        <div className="flex items-center gap-1">
          {[{ label: "Last night", hours: 14 }, { label: "24h", hours: 24 }, { label: "7d", hours: 168 }].map((p) => (
            <button key={p.label} onClick={() => applyPreset(p.hours)}
              className="px-2 py-1.5 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">{p.label}</button>
          ))}
        </div>

        {hasFilters && (
          <button
            onClick={() => { setCameraFilter(""); setDateFrom(""); setDateTo(""); setKindFilter("all"); setPage(0); }}
            className="px-3 py-2 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
            Clear filters
          </button>
        )}
      </div>

      {jumpError && <p className="mb-4 text-xs text-red-400">{jumpError}</p>}

      {loading ? (
        <div className="text-sm text-muted-foreground py-20 text-center">Loading timeline.</div>
      ) : visible.length === 0 ? (
        <EmptyState
          title="Nothing on the timeline yet"
          body="Detections and spoken moments from your cameras show up here as they happen. Widen the date range or clear filters to see more."
          actionLabel={hasFilters ? "Clear filters" : undefined}
          onAction={hasFilters ? () => { setCameraFilter(""); setDateFrom(""); setDateTo(""); setKindFilter("all"); } : undefined}
        />
      ) : (
        <>
          {groups.map((g) => (
            <div key={g.day} className="mb-6">
              <div className="sticky top-0 z-10 -mx-1 mb-2 bg-background/80 backdrop-blur px-1 py-1.5 text-xs font-medium text-muted-foreground">
                {g.day}
              </div>
              <ul className="relative border-l border-border-subtle ml-2">
                {g.items.map((it) => {
                  const isObs = it.kind === "observation";
                  const persons = isObs ? personNames(it) : [];
                  const objects = isObs ? objectLabels(it).filter((o) => o !== "person") : [];
                  return (
                    <li key={`${it.kind}-${it.id}`} className="relative pl-5 pb-4">
                      {/* rail dot */}
                      <span
                        className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-background ${
                          isObs ? "bg-accent" : "bg-amber-400"
                        }`}
                      />
                      <button
                        onClick={() => playMoment(it)}
                        className="w-full text-left rounded-lg border border-border bg-card hover:border-accent/60 hover:bg-card/80 transition-all focus:outline-none focus:ring-1 focus:ring-accent group"
                      >
                        <div className="flex gap-3 p-3">
                          {isObs && it.thumbnail_path ? (
                            <img
                              src={`/api/observations/${it.id}/thumbnail${token ? `?token=${token}` : ""}`}
                              alt=""
                              className="h-16 w-24 shrink-0 rounded object-cover bg-muted"
                              onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }}
                            />
                          ) : (
                            <div className={`h-16 w-24 shrink-0 rounded flex items-center justify-center text-2xl ${isObs ? "bg-muted" : "bg-amber-500/10"}`}>
                              {isObs ? "👁️" : "🔊"}
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                              <span className="font-mono">{clockLabel(it.started_at)}</span>
                              <span>·</span>
                              <span className="truncate">{cameraNames[it.camera_id] || "Unknown camera"}</span>
                              <span className="ml-auto opacity-0 group-hover:opacity-100 text-accent transition-opacity">Play ▶</span>
                            </div>
                            <div className="mt-1 text-sm text-foreground line-clamp-2">
                              {isObs
                                ? (it.vlm_description || "Motion detected")
                                : <span className="italic">“{it.text}”</span>}
                            </div>
                            {(persons.length > 0 || objects.length > 0) && (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {persons.map((p) => (
                                  <span key={p} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] leading-none border border-accent/40 bg-accent/10 text-accent">🧑 {p}</span>
                                ))}
                                {objects.map((o) => (
                                  <span key={o} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] leading-none border border-border bg-muted text-muted-foreground">{OBJECT_GLYPH[o] || "•"} {o}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

          <div className="flex items-center justify-between mt-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}
              className="px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed">Previous</button>
            <span className="text-xs text-muted-foreground">Page {page + 1}</span>
            <button onClick={() => setPage((p) => p + 1)} disabled={!hasNext}
              className="px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed">Next</button>
          </div>
        </>
      )}
    </div>
  );
}
