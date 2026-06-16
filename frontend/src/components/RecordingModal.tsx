"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";

type AnnOpts = { boxes: boolean; captions: boolean; strip: boolean };
const ANN_KEY = "nurby-rec-annotate";
const ANN_TOGGLES: { key: keyof AnnOpts; label: string; title: string }[] = [
  { key: "strip", label: "Timeline strip", title: "Colour-coded pet / human / vehicle bar along the bottom" },
  { key: "boxes", label: "Detection boxes", title: "Bounding boxes for confident detections" },
  { key: "captions", label: "Captions", title: "Burn the AI description onto the video" },
];

function loadAnn(): AnnOpts {
  try {
    const raw = localStorage.getItem(ANN_KEY);
    if (raw) return { boxes: false, captions: false, strip: false, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { boxes: false, captions: false, strip: false };
}

interface RecordingLike {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at?: string | null;
  duration_seconds?: number | null;
  file_size_bytes?: number | null;
}

interface Props {
  recording: RecordingLike | null;
  cameraName?: string | null;
  onClose: () => void;
}

function fmtDateTime(iso: string): string {
  return formatDateTime(iso);
}

function fmtDuration(s: number | null | undefined): string {
  if (!s) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h) return `${h}h ${m}m ${sec}s`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function fmtSize(b: number | null | undefined): string {
  if (!b) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function RecordingModal({ recording, cameraName, onClose }: Props) {
  const { token } = useAuth();
  const tq = token ? `?token=${token}` : "";
  const [ann, setAnn] = useState<AnnOpts>(loadAnn);
  useEffect(() => {
    try { localStorage.setItem(ANN_KEY, JSON.stringify(ann)); } catch { /* ignore */ }
  }, [ann]);
  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [recording, onClose]);

  if (!recording) return null;

  const anyAnn = ann.boxes || ann.captions || ann.strip;
  const dlParams = [
    ...(token ? [`token=${token}`] : []),
    ...(ann.boxes ? ["boxes=1"] : []),
    ...(ann.captions ? ["captions=1"] : []),
    ...(ann.strip ? ["strip=1"] : []),
  ];
  const dlHref = `/api/recordings/${recording.id}/download${dlParams.length ? `?${dlParams.join("&")}` : ""}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">
              {cameraName || "Recording"}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {fmtDateTime(recording.started_at)}
              {recording.duration_seconds != null && (
                <>
                  <span className="mx-2">&middot;</span>
                  {fmtDuration(recording.duration_seconds)}
                </>
              )}
              {recording.file_size_bytes != null && (
                <>
                  <span className="mx-2">&middot;</span>
                  {fmtSize(recording.file_size_bytes)}
                </>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
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
          <video
            key={recording.id}
            controls
            autoPlay
            className="w-full max-h-[60vh] rounded bg-black"
            src={`/api/recordings/${recording.id}/stream${tq}`}
          />
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] text-muted-foreground">Annotate:</span>
              {ANN_TOGGLES.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  title={t.title}
                  onClick={() => setAnn((a) => ({ ...a, [t.key]: !a[t.key] }))}
                  className={`px-2 py-0.5 text-[11px] rounded border transition-colors ${
                    ann[t.key]
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <a
              href={dlHref}
              download
              title={anyAnn ? "Rendered on the server, may take a moment" : undefined}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 transition-opacity"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              {anyAnn ? "Download + annotations" : "Download"}
            </a>
          </div>
          {anyAnn && (
            <p className="text-[11px] text-muted-foreground text-right -mt-1">
              Annotated copies are rendered on the server and may take a moment. The original stays untouched.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
