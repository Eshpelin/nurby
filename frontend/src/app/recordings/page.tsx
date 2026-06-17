"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { EmptyState, CameraGlyph } from "@/components/EmptyState";
import { RecordingDetectionOverlay } from "@/components/RecordingDetectionOverlay";
import { MotionHeatstrip } from "@/components/MotionHeatstrip";

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

const PAGE_SIZE = 24;

export default function RecordingsPage() {
  const { authFetch, token } = useAuth();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [cameraFilter, setCameraFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [objectFilter, setObjectFilter] = useState("");
  const [showBoxes, setShowBoxes] = useState(true);
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

  const fetchCameras = useCallback(async () => {
    try {
      const res = await authFetch("/api/cameras");
      if (res.ok) setCameras(await res.json());
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
    if (objectFilter) params.set("object", objectFilter);
    if (dateFrom) params.set("from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("to", new Date(dateTo).toISOString());
    return params;
  }, [page, cameraFilter, objectFilter, dateFrom, dateTo]);

  const fetchRecordings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`/api/recordings?${buildParams(true).toString()}`);
      if (res.ok) {
        setRecordings(await res.json());
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

  useEffect(() => {
    fetchCameras();
  }, [fetchCameras]);

  useEffect(() => {
    fetchRecordings();
  }, [fetchRecordings]);

  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
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
  }, [expandedId]);

  const expandedRec = useMemo(
    () => recordings.find((r) => r.id === expandedId) || null,
    [recordings, expandedId],
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
    setObjectFilter("");
    setPage(0);
  };

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

      <div className="flex flex-wrap items-center gap-3 mb-6">
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
          value={objectFilter}
          onChange={(e) => { setObjectFilter(e.target.value); setPage(0); }}
          className="px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          title="Only show clips that contain this object"
        >
          <option value="">Any object</option>
          {COMMON_OBJECTS.map((o) => (
            <option key={o} value={o}>{o[0].toUpperCase() + o.slice(1)}</option>
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

        <button
          onClick={downloadRange}
          disabled={recordings.length === 0}
          title="Download every clip matching these filters as a single zip"
          className="px-3 py-2 text-xs rounded-md border border-accent bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-40"
        >
          Download range
        </button>

        {(cameraFilter || dateFrom || dateTo || objectFilter) && (
          <button
            onClick={resetFiltersAndPage}
            className="px-3 py-2 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            Clear filters
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground py-20 text-center">
          Loading recordings.
        </div>
      ) : recordings.length === 0 ? (
        (cameraFilter || dateFrom || dateTo) ? (
          <EmptyState
            title="No recordings match these filters"
            body="Try a different camera or widen the date range."
            actionLabel="Clear filters"
            onAction={() => { setCameraFilter(""); setDateFrom(""); setDateTo(""); }}
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
                onClick={() => setExpandedId(rec.id)}
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
                  seekLabel={objectFilter || null}
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
                      ? `${seekTargets.length} ${objectFilter || "detection"} moment${seekTargets.length === 1 ? "" : "s"}`
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
    </div>
  );
}
