"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { RecordingModal } from "@/components/RecordingModal";
import { formatWith } from "@/lib/time";

// A single moment in time. opens when a user clicks a timestamp on an
// incident/timeline card. Shows the exact analyzed frame for that camera +
// time with what was detected, without touching the live dashboard feed.
// If a recording covers the moment, offers to play it.

interface Detection {
  label?: string;
  confidence?: number;
  plate_text?: string | null;
}
interface FaceDet {
  person_name?: string | null;
}
interface VehicleDet {
  label?: string;
  plate_text?: string | null;
  identity_key?: string | null;
}
interface ObservationDetail {
  id: string;
  camera_id: string;
  started_at: string;
  vlm_description: string | null;
  thumbnail_path: string | null;
  object_detections: { objects?: Detection[] } | null;
  person_detections: { faces?: FaceDet[] } | null;
  vehicle_detections: { vehicles?: VehicleDet[] } | null;
}

interface RecordingLike {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at?: string | null;
  duration_seconds?: number | null;
}

interface VlmPass {
  pass_no: number;
  lens: string;
  model?: string | null;
  provider_name?: string | null;
  description?: string | null;
  attributes?: {
    colors?: string[];
    time_of_day?: string[];
    text_seen?: string[];
    people_count?: number;
  } | null;
  authoritative: boolean;
  created_at?: string | null;
}

export interface MomentModalProps {
  observationId: string;
  cameraId: string;
  cameraName?: string | null;
  ts: string;
  onClose: () => void;
}

export function MomentModal({ observationId, cameraId, cameraName, ts, onClose }: MomentModalProps) {
  const { authFetch, token } = useAuth();
  const [obs, setObs] = useState<ObservationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [recording, setRecording] = useState<RecordingLike | null>(null);
  const [playing, setPlaying] = useState(false);
  const [passes, setPasses] = useState<VlmPass[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authFetch(`/api/observations/${observationId}`);
        if (r.ok && !cancelled) setObs(await r.json());
      } catch {/* ignore */}
      finally { if (!cancelled) setLoading(false); }
      // VLM pass history (versioned enrichment). only interesting when more
      // than the original live pass exists.
      try {
        const pr = await authFetch(`/api/observations/${observationId}/vlm-passes`);
        if (pr.ok && !cancelled) setPasses(await pr.json());
      } catch {/* ignore */}
      // Best-effort. find a recording covering this moment.
      try {
        const rr = await authFetch(`/api/recordings?camera_id=${cameraId}&limit=200`);
        if (rr.ok && !cancelled) {
          const recs: RecordingLike[] = await rr.json();
          const t = new Date(ts).getTime();
          const hit = recs.find((rec) => {
            const s = new Date(rec.started_at).getTime();
            const e = rec.ended_at ? new Date(rec.ended_at).getTime() : s + (rec.duration_seconds || 0) * 1000;
            return t >= s - 2000 && t <= e + 2000;
          });
          if (hit) setRecording(hit);
        }
      } catch {/* ignore */}
    })();
    return () => { cancelled = true; };
  }, [observationId, cameraId, ts, authFetch]);

  const close = useCallback(() => onClose(), [onClose]);

  const when = formatWith(new Date(ts), {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

  const objects = (obs?.object_detections?.objects || []).filter((o) => o.label && o.label !== "license_plate");
  const people = (obs?.person_detections?.faces || []);
  const vehicles = (obs?.vehicle_detections?.vehicles || []);
  const plates = [
    ...objects.map((o) => o.plate_text).filter(Boolean),
    ...vehicles.map((v) => v.plate_text).filter(Boolean),
  ] as string[];

  if (playing && recording) {
    return <RecordingModal recording={recording} cameraName={cameraName} onClose={() => setPlaying(false)} />;
  }

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={close}>
      <div className="w-full max-w-2xl rounded-lg border border-border bg-card shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{cameraName || "Camera"}</div>
            <div className="text-xs text-muted-foreground mt-0.5 font-mono">{when}</div>
          </div>
          <button onClick={close} aria-label="Close" className="shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="p-4 space-y-3">
          {/* The exact analyzed frame at this moment. */}
          <div className="relative w-full rounded-md bg-black overflow-hidden">
            <img
              src={`/api/observations/${observationId}/thumbnail${token ? `?token=${token}` : ""}`}
              alt={`Frame at ${when}`}
              className="w-full max-h-[55vh] object-contain"
            />
            {recording && (
              <button
                onClick={() => setPlaying(true)}
                className="absolute bottom-2 right-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-black/70 text-white hover:bg-black/90 backdrop-blur transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3" /></svg>
                Play recording
              </button>
            )}
          </div>

          {/* What was detected at this moment. */}
          <div className="flex flex-wrap gap-1.5">
            {people.map((p, i) => (
              <span key={`p${i}`} className="text-[11px] px-2 py-0.5 rounded-full bg-green-500/15 text-green-300 border border-green-500/30">
                {p.person_name || "Unknown person"}
              </span>
            ))}
            {vehicles.map((v, i) => (
              <span key={`v${i}`} className="text-[11px] px-2 py-0.5 rounded-full bg-accent/15 text-accent border border-accent/30">
                {v.label || "vehicle"}{v.plate_text ? ` · ${v.plate_text}` : ""}
              </span>
            ))}
            {objects.map((o, i) => (
              <span key={`o${i}`} className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                {o.label}{o.confidence != null ? ` ${Math.round(o.confidence * 100)}%` : ""}
              </span>
            ))}
            {plates.map((pl, i) => (
              <span key={`pl${i}`} className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-300 border border-yellow-500/30">
                🔢 {pl}
              </span>
            ))}
          </div>

          {/* Scene description. */}
          {loading ? (
            <p className="text-xs text-muted-foreground">Loading moment.</p>
          ) : obs?.vlm_description ? (
            <p className="text-sm leading-relaxed text-foreground/90">{obs.vlm_description}</p>
          ) : (
            <p className="text-xs text-muted-foreground italic">No scene description for this frame.</p>
          )}

          {/* Versioned VLM pass history. Pass 1 is the live caption, later
              passes are idle enrichment. Only shown when enrichment ran. */}
          {passes.length > 1 && (
            <div className="rounded-md border border-border bg-muted/20">
              <button
                onClick={() => setShowHistory((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                <span>VLM history · {passes.length} passes</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  className={`transition-transform ${showHistory ? "rotate-180" : ""}`}>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {showHistory && (
                <div className="px-3 pb-3 space-y-2.5">
                  {passes.map((p) => (
                    <div key={p.pass_no} className="text-xs border-l-2 border-border pl-2.5">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-accent/15 text-accent border border-accent/30">
                          {p.lens}
                        </span>
                        {p.authoritative && (
                          <span className="text-[10px] text-green-400">authoritative</span>
                        )}
                        <span className="text-[10px] text-muted-foreground ml-auto font-mono">
                          {p.model || p.provider_name || ""}
                          {p.created_at ? ` · ${formatWith(new Date(p.created_at), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""}
                        </span>
                      </div>
                      {p.description && (
                        <p className="text-foreground/80 leading-snug">{p.description}</p>
                      )}
                      {p.attributes && (p.attributes.colors?.length || p.attributes.text_seen?.length || p.attributes.time_of_day?.length) ? (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {(p.attributes.colors || []).map((c) => (
                            <span key={`c${c}`} className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">{c}</span>
                          ))}
                          {(p.attributes.time_of_day || []).map((t) => (
                            <span key={`t${t}`} className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">{t}</span>
                          ))}
                          {(p.attributes.text_seen || []).map((x) => (
                            <span key={`x${x}`} className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-yellow-500/15 text-yellow-300 border border-yellow-500/30">{x}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-between pt-1">
            <a href={`/cameras/${cameraId}`} className="text-[11px] text-accent hover:underline">
              Open this camera →
            </a>
            {!recording && !loading && (
              <span className="text-[10px] text-muted-foreground">No recording stored for this moment</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
