"use client";

import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  location_label: string | null;
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return "0s";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

type TimeRange = "today" | "7d" | "30d";

export default function TimelinePage() {
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [cameras, setCameras] = useState<Record<string, Camera>>({});
  const [selectedCamera, setSelectedCamera] = useState<string | null>(null);
  const [activeRecording, setActiveRecording] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("7d");
  const [loading, setLoading] = useState(true);

  const fetchCameras = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/cameras`);
      if (!res.ok) return;
      const data: Camera[] = await res.json();
      const map: Record<string, Camera> = {};
      for (const c of data) {
        map[c.id] = c;
      }
      setCameras(map);
    } catch {
      // silently fail
    }
  }, []);

  const fetchRecordings = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (selectedCamera) params.set("camera_id", selectedCamera);
      const res = await fetch(`${API_URL}/api/recordings?${params}`);
      if (!res.ok) return;
      const data: Recording[] = await res.json();

      // Filter by time range
      const now = Date.now();
      const cutoffs: Record<TimeRange, number> = {
        today: 24 * 60 * 60 * 1000,
        "7d": 7 * 24 * 60 * 60 * 1000,
        "30d": 30 * 24 * 60 * 60 * 1000,
      };
      const cutoff = now - cutoffs[timeRange];
      const filtered = data.filter((r) => new Date(r.started_at).getTime() >= cutoff);
      setRecordings(filtered);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [selectedCamera, timeRange]);

  useEffect(() => {
    fetchCameras();
  }, [fetchCameras]);

  useEffect(() => {
    setLoading(true);
    fetchRecordings();
    const interval = setInterval(fetchRecordings, 15000);
    return () => clearInterval(interval);
  }, [fetchRecordings]);

  // Group recordings by date
  const grouped: Record<string, Recording[]> = {};
  for (const r of recordings) {
    const dateKey = formatDate(r.started_at);
    if (!grouped[dateKey]) grouped[dateKey] = [];
    grouped[dateKey].push(r);
  }

  const cameraList = Object.values(cameras);

  return (
    <div className="px-6 py-6">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Timeline</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {recordings.length} recording{recordings.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 p-1 rounded-md bg-card border border-border">
            {(["today", "7d", "30d"] as TimeRange[]).map((range) => (
              <button
                key={range}
                onClick={() => setTimeRange(range)}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  timeRange === range
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {range === "today" ? "Today" : range}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Filter sidebar */}
        <aside className="col-span-3 space-y-5">
          <div>
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
              Camera
            </div>
            {cameraList.length === 0 ? (
              <p className="text-sm text-muted-foreground">No cameras configured</p>
            ) : (
              <div className="space-y-1">
                <button
                  onClick={() => setSelectedCamera(null)}
                  className={`block w-full text-left px-2 py-1.5 text-sm rounded transition-colors ${
                    !selectedCamera
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  All cameras
                </button>
                {cameraList.map((cam) => (
                  <button
                    key={cam.id}
                    onClick={() => setSelectedCamera(cam.id)}
                    className={`block w-full text-left px-2 py-1.5 text-sm rounded transition-colors ${
                      selectedCamera === cam.id
                        ? "bg-muted text-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {cam.name}
                    {cam.location_label && (
                      <span className="ml-1 text-xs text-muted-foreground">
                        {cam.location_label}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Timeline feed */}
        <section className="col-span-9">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="text-sm text-muted-foreground">Loading recordings.</div>
            </div>
          ) : recordings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="w-16 h-16 rounded-full border border-border flex items-center justify-center mb-4 text-muted-foreground text-2xl">
                ?
              </div>
              <p className="text-muted-foreground text-sm">
                No recordings found in this time range.
                Recordings appear here once cameras are connected and the ingestion service is running.
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {Object.entries(grouped).map(([date, recs]) => (
                <div key={date}>
                  <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                    {date}
                  </div>
                  <div className="space-y-2">
                    {recs.map((rec) => {
                      const cam = cameras[rec.camera_id];
                      const isActive = activeRecording === rec.id;

                      return (
                        <div key={rec.id}>
                          <button
                            onClick={() => setActiveRecording(isActive ? null : rec.id)}
                            className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
                              isActive
                                ? "border-accent bg-card"
                                : "border-border hover:border-accent/50 hover:bg-card/50"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                <div className="w-2 h-2 rounded-full bg-green-500" />
                                <div>
                                  <div className="text-sm font-medium">
                                    {cam?.name || "Unknown Camera"}
                                  </div>
                                  <div className="font-mono text-xs text-muted-foreground mt-0.5">
                                    {formatTime(rec.started_at)}
                                    {rec.ended_at && ` \u2192 ${formatTime(rec.ended_at)}`}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-3 text-xs text-muted-foreground font-mono">
                                <span>{formatDuration(rec.duration_seconds)}</span>
                                <span>{formatSize(rec.file_size_bytes)}</span>
                              </div>
                            </div>
                          </button>

                          {isActive && (
                            <div className="mt-2 rounded-lg overflow-hidden border border-border bg-black">
                              <video
                                controls
                                autoPlay
                                className="w-full aspect-video"
                                src={`${API_URL}/api/recordings/${rec.id}/stream`}
                              >
                                Your browser does not support video playback.
                              </video>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
