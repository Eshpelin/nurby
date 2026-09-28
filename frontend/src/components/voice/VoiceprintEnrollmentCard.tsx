"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

type Clip = {
  transcript_id: string;
  audio_url: string | null;
  camera_name: string | null;
  started_at: string;
  duration_seconds: number;
  transcript: string;
  speaker_confidence: number | null;
  attribution_reason: string;
  audio_available: boolean;
  review_status: "candidate" | "confirmed" | "rejected" | "removed";
  consent_given: boolean;
  quality?: {
    eligible: boolean;
    duration_ok: boolean;
    audio_retained: boolean;
    visual_attribution_ok: boolean;
    reasons: string[];
  };
  attribution_model_version?: string;
};

type VoiceprintEnrollmentCardProps = { personId: string };

export function VoiceprintEnrollmentCard({ personId }: VoiceprintEnrollmentCardProps) {
  const { authFetch, token } = useAuth();
  const [clips, setClips] = useState<Clip[]>([]);
  const [includeRejected, setIncludeRejected] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trainingMessage, setTrainingMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await authFetch(
        `/api/voiceprints/persons/${personId}/candidates${includeRejected ? "?include_rejected=true" : ""}`,
      );
      if (!response.ok) throw new Error(`Voice clips unavailable (${response.status})`);
      const body = await response.json() as { candidates: Clip[]; training_message?: string };
      setClips(body.candidates);
      setTrainingMessage(body.training_message ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice clips unavailable");
    } finally {
      setLoading(false);
    }
  }, [authFetch, includeRejected, personId]);

  useEffect(() => { void load(); }, [load]);

  const decide = async (clipIds: string[], decision: "confirm" | "reject" | "reopen" | "remove") => {
    if (clipIds.length === 0) return;
    setBusy(true);
    try {
      for (const transcriptId of clipIds) {
        const response = await authFetch(`/api/voiceprints/persons/${personId}/candidates/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transcript_id: transcriptId, decision, consent_given: decision === "confirm" && consent }),
        });
        if (!response.ok) throw new Error(`Could not ${decision} voice clip (${response.status})`);
      }
      setSelected(new Set());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice clip decision failed");
    } finally {
      setBusy(false);
    }
  };

  const candidates = clips.filter((clip) => clip.review_status === "candidate");
  const confirmed = clips.filter((clip) => clip.review_status === "confirmed");
  const rejected = clips.filter((clip) => clip.review_status === "rejected");

  return (
    <section className="mb-4 rounded-md border border-border bg-card/40 p-3" aria-label="Voiceprint enrollment">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Voiceprint enrollment</div>
          <p className="mt-1 text-xs text-muted-foreground">
            No recording or uploaded sample is required. Review existing clips that were attributed to this person by camera evidence.
          </p>
        </div>
        <button type="button" onClick={() => void load()} className="text-[10px] text-muted-foreground hover:text-foreground">Refresh</button>
      </div>
      {trainingMessage && <p className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px] text-amber-200">{trainingMessage}</p>}
      {loading ? <p className="py-3 text-xs text-muted-foreground">Finding eligible clips…</p> : error ? <p className="py-3 text-xs text-red-400">{error}</p> : (
        <>
          {candidates.length === 0 && confirmed.length === 0 && <p className="py-3 text-xs text-muted-foreground">No eligible attributed audio clips are available.</p>}
          <div className="mt-2 space-y-2">
            {candidates.map((clip) => (
              <div key={clip.transcript_id} className="rounded border border-border/70 p-2">
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    aria-label={`Select voice clip from ${new Date(clip.started_at).toLocaleString()}`}
                    checked={selected.has(clip.transcript_id)}
                    onChange={(event) => setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(clip.transcript_id); else next.delete(clip.transcript_id);
                      return next;
                    })}
                    className="mt-1 accent-accent"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-medium">{clip.camera_name ?? "Camera"} · {new Date(clip.started_at).toLocaleString()}</div>
                    <div className="text-[10px] text-muted-foreground">{clip.duration_seconds}s · {Math.round((clip.speaker_confidence ?? 0) * 100)}% visual attribution</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">{clip.attribution_reason}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      Quality: {clip.quality?.eligible ? "eligible" : `not eligible (${clip.quality?.reasons.join(", ") || "needs review"})`} · source {clip.attribution_model_version ?? "video-correlated-v1"}
                    </div>
                    {clip.transcript && <div className="mt-1 text-xs text-foreground/90">“{clip.transcript}”</div>}
                    {clip.audio_available && clip.audio_url && (
                      <audio className="mt-1 h-7 w-full" controls preload="none" src={`${clip.audio_url}${token ? `?token=${encodeURIComponent(token)}` : ""}`} />
                    )}
                  </div>
                  <button type="button" onClick={() => void decide([clip.transcript_id], "reject")} disabled={busy} className="text-[10px] text-muted-foreground hover:text-foreground">Not this person</button>
                </div>
              </div>
            ))}
          </div>
          {candidates.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="accent-accent" />
                I consent to using the selected clips to derive this person’s voiceprint.
              </label>
              <button type="button" onClick={() => void decide([...selected], "confirm")} disabled={busy || selected.size === 0 || !consent} className="rounded border border-accent px-2 py-1 text-[10px] text-accent disabled:opacity-50">Confirm selected clips</button>
            </div>
          )}
          {confirmed.length > 0 && (
            <div className="mt-3 border-t border-border/60 pt-2">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Confirmed source clips ({confirmed.length})</div>
              <div className="mt-1 space-y-1">
                {confirmed.map((clip) => <div key={clip.transcript_id} className="flex items-center justify-between text-[10px] text-muted-foreground"><span>{new Date(clip.started_at).toLocaleString()} · {clip.camera_name ?? "Camera"}</span><button type="button" onClick={() => void decide([clip.transcript_id], "remove")} disabled={busy} className="text-muted-foreground hover:text-foreground">Remove from set</button></div>)}
              </div>
            </div>
          )}
          <label className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <input type="checkbox" checked={includeRejected} onChange={(event) => setIncludeRejected(event.target.checked)} className="accent-accent" />
            Show previously rejected clips so I can deliberately reopen them.
          </label>
          {includeRejected && rejected.map((clip) => <div key={clip.transcript_id} className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground"><span>{new Date(clip.started_at).toLocaleString()} · Rejected</span><button type="button" onClick={() => void decide([clip.transcript_id], "reopen")} disabled={busy} className="text-accent hover:underline">Reopen</button></div>)}
        </>
      )}
    </section>
  );
}
