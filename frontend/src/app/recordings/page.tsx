"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { EmptyState, CameraGlyph } from "@/components/EmptyState";
import { RecordingDetectionOverlay } from "@/components/RecordingDetectionOverlay";
import { MotionHeatstrip } from "@/components/MotionHeatstrip";
import { MotionReviewItems } from "@/components/MotionReviewItems";
import { ShareDialog } from "@/components/ShareDialog";

// Objects people most often scrub for. Free of a fixed list otherwise.
const COMMON_OBJECTS = ["person", "cat", "dog", "car", "truck", "bus", "bicycle", "motorcycle"];

// datetime-local <input> value (local time, no seconds) for a Date.
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface Recording {
  id: string;
  camera_id: string;
  file_path: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  thumbnail_path: string | null;
}

interface Camera {
  id: string;
  name: string;
  width?: number | null;
  height?: number | null;
}

interface Person {
  id: string;
  display_name: string;
  nickname?: string | null;
}

interface Vehicle {
  id: string;
  display_name: string;
  license_plate?: string | null;
  vehicle_type?: string | null;
}

// Per-recording activity summary shown as chips on each card.
interface Facet {
  objects: string[];
  persons: string[];
  vehicles: string[];
  has_audio: boolean;
}

// A speech transcript hit from /transcripts (used by the "search what was
// said" mode to jump into the covering recording at the right moment).
interface Transcript {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at: string | null;
  text: string;
}

// A small emoji glyph per object class, so a card scans at a glance.
const OBJECT_GLYPH: Record<string, string> = {
  person: "🧍", cat: "🐈", dog: "🐕", car: "🚗", truck: "🚚",
  bus: "🚌", bicycle: "🚲", motorcycle: "🏍️", bird: "🐦",
};

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "unknown";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatFileSize(bytes: number | null): string {
  if (bytes == null) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

// Seconds -> m:ss (or h:mm:ss), for clip in/out markers.
function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

// Small activity chips on a recording card: what was seen during the clip.
// A recording links to detections only by time overlap, so these come from the
// /facets endpoint rather than the recording row itself.
function FacetChips({ facet }: { facet: Facet | undefined }) {
  if (!facet) return null;
  const { objects, persons, vehicles, has_audio } = facet;
  if (
    objects.length === 0 && persons.length === 0 &&
    vehicles.length === 0 && !has_audio
  ) {
    return null;
  }
  const chip = "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] leading-none border";
  return (
    <div className="flex flex-wrap gap-1 pt-1">
      {persons.map((p) => (
        <span key={`p-${p}`} className={`${chip} border-accent/40 bg-accent/10 text-accent`} title={`Person: ${p}`}>
          🧑 {p}
        </span>
      ))}
      {vehicles.map((v) => (
        <span key={`v-${v}`} className={`${chip} border-amber-500/40 bg-amber-500/10 text-amber-300`} title={`Vehicle: ${v}`}>
          🚗 {v}
        </span>
      ))}
      {objects
        .filter((o) => o !== "person")
        .map((o) => (
          <span key={`o-${o}`} className={`${chip} border-border bg-muted text-muted-foreground`} title={`Object: ${o}`}>
            {OBJECT_GLYPH[o] || "•"} {o}
          </span>
        ))}
      {has_audio && (
        <span className={`${chip} border-border bg-muted text-muted-foreground`} title="Has audio transcript">
          🔊 audio
        </span>
      )}
    </div>
  );
}

const PAGE_SIZE = 24;

export default function RecordingsPage() {
  const { authFetch, token } = useAuth();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [facets, setFacets] = useState<Record<string, Facet>>({});
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [cameraFilter, setCameraFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [objectFilters, setObjectFilters] = useState<string[]>([]);
  const [personFilter, setPersonFilter] = useState("");
  const [vehicleFilter, setVehicleFilter] = useState("");
  const [showBoxes, setShowBoxes] = useState(true);
  // "Search what was said" mode: transcript full-text search that deep-links
  // into the covering recording, seeked to the utterance.
  const [speechQuery, setSpeechQuery] = useState("");
  const [speechResults, setSpeechResults] = useState<Transcript[] | null>(null);
  const [speechLoading, setSpeechLoading] = useState(false);
  const [speechError, setSpeechError] = useState<string | null>(null);
  // A recording resolved from a transcript hit that may not be on the current
  // grid page, so the modal can still open it.
  const [directRec, setDirectRec] = useState<Recording | null>(null);
  // Seconds to seek the player to once its metadata loads (from a speech hit).
  const pendingSeekRef = useRef<number | null>(null);
  // Trim/clip export: in/out points (seconds into the recording) for the
  // server-side clip cut. Null until the user marks them.
  const [clipStart, setClipStart] = useState<number | null>(null);
  const [clipEnd, setClipEnd] = useState<number | null>(null);

  const toggleObject = useCallback((obj: string) => {
    setObjectFilters((prev) =>
      prev.includes(obj) ? prev.filter((o) => o !== obj) : [...prev, obj],
    );
    setPage(0);
  }, []);
  const [seekTargets, setSeekTargets] = useState<number[]>([]);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Jump the playhead to the next/previous detection (of the filtered object,
  // or any). Reads currentTime from the element directly (event handler).
  const seekToDetection = useCallback((dir: 1 | -1) => {
    const v = videoRef.current;
    if (!v || seekTargets.length === 0) return;
    const cur = v.currentTime;
    const eps = 0.4;
    const target = dir > 0
      ? seekTargets.find((o) => o > cur + eps)
      : [...seekTargets].reverse().find((o) => o < cur - eps);
    if (target != null) {
      v.currentTime = target;
      v.play?.().catch(() => undefined);
    }
  }, [seekTargets]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Recording being shared via an anonymous link (opens ShareDialog).
  const [shareRec, setShareRec] = useState<Recording | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const cameraNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of cameras) map[c.id] = c.name;
    return map;
  }, [cameras]);
  const cameraById = useMemo(() => {
    const map: Record<string, Camera> = {};
    for (const c of cameras) map[c.id] = c;
    return map;
  }, [cameras]);

  const fetchPickers = useCallback(async () => {
    try {
      const [cRes, pRes, vRes] = await Promise.all([
        authFetch("/api/cameras"),
        authFetch("/api/persons"),
        authFetch("/api/vehicles"),
      ]);
      if (cRes.ok) setCameras(await cRes.json());
      if (pRes.ok) setPersons(await pRes.json());
      if (vRes.ok) setVehicles(await vRes.json());
    } catch {
      /* silent */
    }
  }, []);

  // Shared query params for the list and the range-download bundle. The
  // datetime-local inputs are local time; send ISO. `paginate` adds the page
  // window (the bundle wants the whole range, not one page).
  const buildParams = useCallback((paginate: boolean) => {
    const params = new URLSearchParams();
    if (paginate) {
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(page * PAGE_SIZE));
    }
    if (cameraFilter) params.set("camera_id", cameraFilter);
    for (const obj of objectFilters) params.append("object", obj);
    if (personFilter) params.set("person_id", personFilter);
    if (vehicleFilter) params.set("vehicle_id", vehicleFilter);
    if (dateFrom) params.set("from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("to", new Date(dateTo).toISOString());
    return params;
  }, [page, cameraFilter, objectFilters, personFilter, vehicleFilter, dateFrom, dateTo]);

  const fetchRecordings = useCallback(async () => {
    setLoading(true);
    setFacets({});
    try {
      const res = await authFetch(`/api/recordings?${buildParams(true).toString()}`);
      if (res.ok) {
        const recs: Recording[] = await res.json();
        setRecordings(recs);
        // Fetch activity chips for this page in one shot (best-effort).
        if (recs.length > 0) {
          try {
            const ids = recs.map((r) => r.id).join(",");
            const fRes = await authFetch(`/api/recordings/facets?ids=${encodeURIComponent(ids)}`);
            if (fRes.ok) setFacets(await fRes.json());
          } catch {
            /* chips are optional */
          }
        }
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [buildParams, authFetch]);

  const downloadRange = () => {
    const params = buildParams(false);
    if (token) params.set("token", token);
    window.open(`/api/recordings/download-bundle?${params.toString()}`, "_blank");
  };

  // Speech search: find transcripts matching the query (respecting the camera
  // and date filters), so the user can jump to "when someone said X".
  const runSpeechSearch = useCallback(async () => {
    const q = speechQuery.trim();
    if (!q) {
      setSpeechResults(null);
      setSpeechError(null);
      return;
    }
    setSpeechLoading(true);
    setSpeechError(null);
    try {
      const params = new URLSearchParams({ search: q, limit: "50" });
      if (cameraFilter) params.set("camera_id", cameraFilter);
      if (dateFrom) params.set("from", new Date(dateFrom).toISOString());
      if (dateTo) params.set("to", new Date(dateTo).toISOString());
      const res = await authFetch(`/api/transcripts?${params.toString()}`);
      if (res.ok) {
        setSpeechResults(await res.json());
      } else {
        setSpeechError("Speech search failed.");
      }
    } catch {
      setSpeechError("Speech search failed.");
    } finally {
      setSpeechLoading(false);
    }
  }, [speechQuery, cameraFilter, dateFrom, dateTo, authFetch]);

  // Open the recording covering a given camera + instant, seeked to it, with a
  // ~30s clip pre-armed around the moment. A recording links to a detection or
  // transcript only by time overlap, so resolve it by querying that camera's
  // recordings around the instant. Returns an error string, or null on success.
  const openAtMoment = useCallback(async (cameraId: string, isoTs: string): Promise<string | null> => {
    const ts = new Date(isoTs);
    const params = new URLSearchParams({
      camera_id: cameraId,
      from: new Date(ts.getTime() - 2000).toISOString(),
      to: new Date(ts.getTime() + 2000).toISOString(),
      limit: "1",
    });
    try {
      const res = await authFetch(`/api/recordings?${params.toString()}`);
      const recs: Recording[] = res.ok ? await res.json() : [];
      const rec = recs[0];
      if (!rec) {
        return "No recording covers that moment (footage already rotated out).";
      }
      const offset = Math.max(0, (ts.getTime() - new Date(rec.started_at).getTime()) / 1000);
      pendingSeekRef.current = offset;
      setDirectRec(rec);
      setClipStart(Math.max(0, offset - 3));
      setClipEnd(offset + 27);
      setExpandedId(rec.id);
      return null;
    } catch {
      return "Could not open that recording.";
    }
  }, [authFetch]);

  const openTranscriptHit = useCallback(async (t: Transcript) => {
    const err = await openAtMoment(t.camera_id, t.started_at);
    if (err) setSpeechError(err);
  }, [openAtMoment]);

  // Hand-off from the Timeline page: it stashes {camera_id, started_at} in
  // sessionStorage then routes here; open that moment on mount.
  useEffect(() => {
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem("nurby_open_moment");
      if (raw) sessionStorage.removeItem("nurby_open_moment");
    } catch {
      /* private mode / no storage */
    }
    if (!raw) return;
    try {
      const { camera_id, started_at } = JSON.parse(raw);
      if (camera_id && started_at) openAtMoment(camera_id, started_at);
    } catch {
      /* malformed hand-off, ignore */
    }
  }, [openAtMoment]);

  useEffect(() => {
    fetchPickers();
  }, [fetchPickers]);

  useEffect(() => {
    fetchRecordings();
  }, [fetchRecordings]);

  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // The share dialog stacks on top and owns Escape while open.
        if (shareRec) return;
        setExpandedId(null);
        setConfirmDeleteId(null);
        setDeleteError(null);
      }
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [expandedId, shareRec]);

  const expandedRec = useMemo(
    () =>
      recordings.find((r) => r.id === expandedId) ||
      (directRec && directRec.id === expandedId ? directRec : null),
    [recordings, expandedId, directRec],
  );

  const handleDelete = useCallback(async (id: string) => {
    setDeletingId(id);
    setDeleteError(null);
    try {
      const res = await authFetch(`/api/recordings/${id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const body = await res.text().catch(() => "");
        throw new Error(body || `Delete failed (${res.status})`);
      }
      setRecordings((prev) => prev.filter((r) => r.id !== id));
      if (expandedId === id) setExpandedId(null);
      setConfirmDeleteId(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }, [authFetch, expandedId]);

  const resetFiltersAndPage = () => {
    setCameraFilter("");
    setDateFrom("");
    setDateTo("");
    setObjectFilters([]);
    setPersonFilter("");
    setVehicleFilter("");
    setPage(0);
  };

  const hasActiveFilters =
    !!cameraFilter || !!dateFrom || !!dateTo ||
    objectFilters.length > 0 || !!personFilter || !!vehicleFilter;

  const applyPreset = (hours: number) => {
    const now = new Date();
    setDateTo(toLocalInput(now));
    setDateFrom(toLocalInput(new Date(now.getTime() - hours * 3600 * 1000)));
    setPage(0);
  };

  const hasNextPage = recordings.length === PAGE_SIZE;
  const hasPrevPage = page > 0;

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Recordings</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {recordings.length} recording{recordings.length !== 1 ? "s" : ""}{" "}
            on this page
          </p>
        </div>
      </div>

      <div className="space-y-3 mb-6">
        {/* Row 1: who / where / when */}
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={cameraFilter}
            onChange={(e) => {
              setCameraFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="">All cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>

          <select
            value={personFilter}
            onChange={(e) => { setPersonFilter(e.target.value); setPage(0); }}
            className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40"
            disabled={persons.length === 0}
            title="Only show clips where this person was seen"
          >
            <option value="">Anyone</option>
            {persons.map((p) => (
              <option key={p.id} value={p.id}>
                {p.nickname || p.display_name}
              </option>
            ))}
          </select>

          <select
            value={vehicleFilter}
            onChange={(e) => { setVehicleFilter(e.target.value); setPage(0); }}
            className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40"
            disabled={vehicles.length === 0}
            title="Only show clips where this vehicle was seen"
          >
            <option value="">Any vehicle</option>
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.license_plate || v.display_name}
              </option>
            ))}
          </select>

          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground">From</label>
            <input
              type="datetime-local"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
              className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground">To</label>
            <input
              type="datetime-local"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
              className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          <div className="flex items-center gap-1">
            {[
              { label: "Last night", hours: 14 },
              { label: "24h", hours: 24 },
              { label: "7d", hours: 168 },
            ].map((p) => (
              <button
                key={p.label}
                onClick={() => applyPreset(p.hours)}
                className="px-2 py-1.5 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              >{p.label}</button>
            ))}
          </div>
        </div>

        {/* Row 2: object-class multi-select chips + actions */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground mr-1">Contains</span>
          {COMMON_OBJECTS.map((o) => {
            const on = objectFilters.includes(o);
            return (
              <button
                key={o}
                onClick={() => toggleObject(o)}
                aria-pressed={on}
                className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                  on
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-border text-muted-foreground hover:text-foreground hover:bg-muted"
                }`}
              >
                <span className="mr-1">{OBJECT_GLYPH[o] || "•"}</span>
                {o[0].toUpperCase() + o.slice(1)}
              </button>
            );
          })}

          <div className="flex-1" />

          <button
            onClick={downloadRange}
            disabled={recordings.length === 0}
            title="Download every clip matching these filters as a single zip"
            className="px-3 py-2 text-xs rounded-md border border-accent bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-40"
          >
            Download range
          </button>

          {hasActiveFilters && (
            <button
              onClick={resetFiltersAndPage}
              className="px-3 py-2 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              Clear filters
            </button>
          )}
        </div>

        {/* Row 3: search what was said (transcripts) */}
        <form
          onSubmit={(e) => { e.preventDefault(); runSpeechSearch(); }}
          className="flex items-center gap-2"
        >
          <div className="relative flex-1 max-w-xl">
            <svg
              width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              value={speechQuery}
              onChange={(e) => setSpeechQuery(e.target.value)}
              placeholder="Search what was said… (e.g. “gate”, “package”, a name)"
              className="w-full pl-8 pr-3 py-2 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <button
            type="submit"
            disabled={!speechQuery.trim() || speechLoading}
            className="px-3 py-2 text-xs rounded-md border border-accent bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-40"
          >
            {speechLoading ? "Searching…" : "Search speech"}
          </button>
          {speechResults !== null && (
            <button
              type="button"
              onClick={() => { setSpeechQuery(""); setSpeechResults(null); setSpeechError(null); }}
              className="px-3 py-2 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              Clear
            </button>
          )}
        </form>
      </div>

      {/* Speech search results: click a line to jump into the recording at that moment. */}
      {speechResults !== null && (
        <div className="mb-6 rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border text-xs text-muted-foreground">
            {speechResults.length === 0
              ? "No speech matched that search."
              : `${speechResults.length} spoken moment${speechResults.length === 1 ? "" : "s"} matched "${speechQuery.trim()}"`}
          </div>
          {speechError && (
            <div className="px-4 py-2 text-xs text-red-400 border-b border-border">{speechError}</div>
          )}
          <ul className="divide-y divide-border-subtle max-h-80 overflow-y-auto">
            {speechResults.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => openTranscriptHit(t)}
                  className="w-full text-left px-4 py-2.5 flex items-start gap-3 hover:bg-muted/60 transition-colors group"
                >
                  <span className="shrink-0 mt-0.5 text-accent">🔊</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-foreground truncate group-hover:whitespace-normal">
                      {t.text}
                    </span>
                    <span className="block text-[11px] text-muted-foreground mt-0.5">
                      {cameraNames[t.camera_id] || "Unknown camera"}
                      <span className="mx-1.5">·</span>
                      {formatDateTime(t.started_at)}
                    </span>
                  </span>
                  <span className="shrink-0 self-center text-[11px] text-muted-foreground group-hover:text-accent">
                    Play ▶
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {loading ? (
        <div className="text-sm text-muted-foreground py-20 text-center">
          Loading recordings.
        </div>
      ) : recordings.length === 0 ? (
        hasActiveFilters ? (
          <EmptyState
            title="No recordings match these filters"
            body="Try a different camera, person, or object, or widen the date range."
            actionLabel="Clear filters"
            onAction={resetFiltersAndPage}
          />
        ) : (
          <EmptyState
            icon={<CameraGlyph />}
            title="No recordings yet"
            body="Recordings appear here as your cameras capture clips. Make sure a camera is connected and its recording mode is set to continuous, motion, or clip in its settings."
            actionLabel="Go to cameras"
            actionHref="/"
          />
        )
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {recordings.map((rec) => (
              <button
                key={rec.id}
                type="button"
                onClick={() => {
                  pendingSeekRef.current = null;
                  setClipStart(null);
                  setClipEnd(null);
                  setExpandedId(rec.id);
                }}
                className="group text-left rounded-lg border border-border bg-card overflow-hidden hover:border-accent/60 hover:bg-card/80 transition-all focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {rec.thumbnail_path ? (
                  <img
                    src={`/api/recordings/${rec.id}/thumbnail`}
                    alt="Recording thumbnail"
                    className="w-full h-36 object-cover bg-muted"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                ) : (
                  <div className="w-full h-36 bg-muted flex items-center justify-center">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground">
                      <polygon points="5,3 19,12 5,21" />
                    </svg>
                  </div>
                )}
                <div className="p-3 space-y-1.5">
                  <div className="text-sm font-medium truncate">
                    {cameraNames[rec.camera_id] || "Unknown camera"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatDateTime(rec.started_at)}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{formatDuration(rec.duration_seconds)}</span>
                    <span>{formatFileSize(rec.file_size_bytes)}</span>
                  </div>
                  <FacetChips facet={facets[rec.id]} />
                </div>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-6">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={!hasPrevPage}
              className="px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-xs text-muted-foreground">
              Page {page + 1}
            </span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={!hasNextPage}
              className="px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </>
      )}

      {expandedRec && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onClick={() => {
            setExpandedId(null);
            setConfirmDeleteId(null);
            setDeleteError(null);
          }}
        >
          <div
            className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-border">
              <div className="min-w-0">
                <div className="text-sm font-medium truncate">
                  {cameraNames[expandedRec.camera_id] || "Unknown camera"}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {formatDateTime(expandedRec.started_at)}
                  <span className="mx-2">&middot;</span>
                  {formatDuration(expandedRec.duration_seconds)}
                  <span className="mx-2">&middot;</span>
                  {formatFileSize(expandedRec.file_size_bytes)}
                </div>
              </div>
              <button
                onClick={() => {
                  setExpandedId(null);
                  setConfirmDeleteId(null);
                  setDeleteError(null);
                }}
                aria-label="Close"
                className="shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="relative w-full">
                <video
                  key={expandedRec.id}
                  ref={videoRef}
                  controls
                  autoPlay
                  className="w-full max-h-[60vh] rounded bg-black"
                  src={`/api/recordings/${expandedRec.id}/stream${token ? `?token=${token}` : ""}`}
                  onLoadedMetadata={(e) => {
                    // Apply a pending seek from a speech-search jump, once.
                    if (pendingSeekRef.current != null) {
                      const v = e.currentTarget;
                      v.currentTime = Math.min(pendingSeekRef.current, v.duration || pendingSeekRef.current);
                      pendingSeekRef.current = null;
                    }
                  }}
                />
                <RecordingDetectionOverlay
                  cameraId={expandedRec.camera_id}
                  startedAt={expandedRec.started_at}
                  endedAt={expandedRec.ended_at}
                  durationSeconds={expandedRec.duration_seconds}
                  camWidth={cameraById[expandedRec.camera_id]?.width}
                  camHeight={cameraById[expandedRec.camera_id]?.height}
                  videoRef={videoRef}
                  draw={showBoxes}
                  seekLabel={objectFilters[0] || null}
                  onTargets={setSeekTargets}
                />
              </div>
              <MotionHeatstrip
                cameraId={expandedRec.camera_id}
                startedAt={expandedRec.started_at}
                endedAt={expandedRec.ended_at}
                durationSeconds={expandedRec.duration_seconds}
                videoRef={videoRef}
              />
              <MotionReviewItems
                cameraId={expandedRec.camera_id}
                startedAt={expandedRec.started_at}
                endedAt={expandedRec.ended_at}
                durationSeconds={expandedRec.duration_seconds}
                videoRef={videoRef}
              />
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => seekToDetection(-1)}
                    disabled={seekTargets.length === 0}
                    className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
                    title="Jump to the previous detection"
                  >◀ Prev</button>
                  <button
                    onClick={() => seekToDetection(1)}
                    disabled={seekTargets.length === 0}
                    className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
                    title="Jump to the next detection"
                  >Next ▶</button>
                  <span className="text-[11px] text-muted-foreground">
                    {seekTargets.length > 0
                      ? `${seekTargets.length} ${objectFilters[0] || "detection"} moment${seekTargets.length === 1 ? "" : "s"}`
                      : "no detections"}
                  </span>
                </div>
                <button
                  onClick={() => setShowBoxes((v) => !v)}
                  className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                    showBoxes
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                  title="Overlay detection boxes on playback"
                >
                  Detections {showBoxes ? "on" : "off"}
                </button>
              </div>

              {/* Clip trim: mark in/out from the playhead, download just that span. */}
              <div className="flex items-center gap-2 flex-wrap rounded-md border border-border-subtle bg-background/40 px-3 py-2">
                <span className="text-[11px] font-medium text-muted-foreground mr-1">Trim clip</span>
                <button
                  onClick={() => {
                    const t = videoRef.current?.currentTime ?? 0;
                    setClipStart(t);
                    if (clipEnd != null && clipEnd <= t) setClipEnd(null);
                  }}
                  className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                  title="Set clip start to the current playhead"
                >Set start{clipStart != null ? ` · ${formatClock(clipStart)}` : ""}</button>
                <button
                  onClick={() => {
                    const t = videoRef.current?.currentTime ?? 0;
                    setClipEnd(t);
                    if (clipStart != null && clipStart >= t) setClipStart(null);
                  }}
                  className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                  title="Set clip end to the current playhead"
                >Set end{clipEnd != null ? ` · ${formatClock(clipEnd)}` : ""}</button>
                {clipStart != null && clipEnd != null && clipEnd > clipStart && (
                  <span className="text-[11px] text-muted-foreground">
                    {formatClock(clipEnd - clipStart)} selected
                  </span>
                )}
                <div className="flex-1" />
                {(clipStart != null || clipEnd != null) && (
                  <button
                    onClick={() => { setClipStart(null); setClipEnd(null); }}
                    className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                  >Reset</button>
                )}
                <a
                  href={
                    clipStart != null && clipEnd != null && clipEnd > clipStart
                      ? `/api/recordings/${expandedRec.id}/clip?start=${clipStart.toFixed(2)}&end=${clipEnd.toFixed(2)}${token ? `&token=${token}` : ""}`
                      : undefined
                  }
                  download
                  aria-disabled={!(clipStart != null && clipEnd != null && clipEnd > clipStart)}
                  onClick={(e) => {
                    if (!(clipStart != null && clipEnd != null && clipEnd > clipStart)) e.preventDefault();
                  }}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                    clipStart != null && clipEnd != null && clipEnd > clipStart
                      ? "border-accent bg-accent/10 text-accent hover:bg-accent/20"
                      : "border-border text-muted-foreground opacity-40 cursor-not-allowed"
                  }`}
                  title="Download only the selected span as its own mp4"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  Download clip
                </a>
              </div>
              {confirmDeleteId === expandedRec.id ? (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2">
                  <span className="text-xs text-red-300 flex-1 min-w-[180px]">
                    Delete this recording and its file?
                  </span>
                  <button
                    onClick={() => handleDelete(expandedRec.id)}
                    disabled={deletingId === expandedRec.id}
                    className="px-3 py-1.5 text-sm rounded-md bg-red-600 text-white font-medium hover:bg-red-500 transition-colors disabled:opacity-50"
                  >
                    {deletingId === expandedRec.id ? "Deleting." : "Yes, delete"}
                  </button>
                  <button
                    onClick={() => {
                      setConfirmDeleteId(null);
                      setDeleteError(null);
                    }}
                    disabled={deletingId === expandedRec.id}
                    className="px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <a
                      href={`/api/recordings/${expandedRec.id}/download${token ? `?token=${token}` : ""}`}
                      download
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 transition-opacity"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      Download
                    </a>
                    <button
                      onClick={() => setShareRec(expandedRec)}
                      title="Create an anonymous link anyone can open until it expires"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="18" cy="5" r="3" />
                        <circle cx="6" cy="12" r="3" />
                        <circle cx="18" cy="19" r="3" />
                        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                      </svg>
                      Share
                    </button>
                  </div>
                  <button
                    onClick={() => {
                      setConfirmDeleteId(expandedRec.id);
                      setDeleteError(null);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
                    </svg>
                    Delete
                  </button>
                </div>
              )}
              {deleteError && confirmDeleteId === expandedRec.id && (
                <p className="text-xs text-red-400">{deleteError}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {shareRec && (
        <ShareDialog
          kind="recording"
          resourceId={shareRec.id}
          label={`${cameraNames[shareRec.camera_id] || "Unknown camera"} · ${formatDateTime(shareRec.started_at)}`}
          onClose={() => setShareRec(null)}
        />
      )}
    </div>
  );
}
