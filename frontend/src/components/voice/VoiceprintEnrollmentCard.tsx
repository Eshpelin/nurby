"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";

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
  const { authFetch, token, user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = useCallback((key: string, values?: Record<string, string | number>) => translate(locale, key, values), [locale]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [includeRejected, setIncludeRejected] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trainingMessage, setTrainingMessage] = useState<string | null>(null);
  const [trainingStatus, setTrainingStatus] = useState<string>("not_ready");
  const [trainingSampleCount, setTrainingSampleCount] = useState(0);
  const [trainingModel, setTrainingModel] = useState<string | null>(null);
  const [trainingQuality, setTrainingQuality] = useState<string>("unavailable");
  const [matchingEnabled, setMatchingEnabled] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await authFetch(
        `/api/voiceprints/persons/${personId}/candidates${includeRejected ? "?include_rejected=true" : ""}`,
      );
      if (!response.ok) throw new Error(`Voice clips unavailable (${response.status})`);
      const body = await response.json() as {
        candidates: Clip[];
        training_message?: string;
        training_status?: string;
        training_sample_count?: number;
        training_model_version?: string | null;
        training_quality?: { status?: string };
        matching_enabled?: boolean;
      };
      setClips(body.candidates);
      setTrainingMessage(body.training_message ?? null);
      setTrainingStatus(body.training_status ?? "not_ready");
      setTrainingSampleCount(body.training_sample_count ?? 0);
      setTrainingModel(body.training_model_version ?? null);
      setTrainingQuality(body.training_quality?.status ?? "unavailable");
      setMatchingEnabled(body.matching_enabled ?? false);
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

  const revoke = async () => {
    if (!window.confirm(t("voiceprint.revoke_help"))) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/voiceprints/persons/${personId}/profile`, { method: "DELETE" });
      if (!response.ok) throw new Error(`Could not revoke voiceprint (${response.status})`);
      setSelected(new Set());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voiceprint revocation failed");
    } finally {
      setBusy(false);
    }
  };

  const reprocess = async () => {
    setReprocessing(true);
    setError(null);
    try {
      const response = await authFetch(`/api/voiceprints/persons/${personId}/reprocess`, { method: "POST" });
      const body = await response.json().catch(() => ({})) as { processed?: number; matched?: number; fused?: number; conflicts?: number; detail?: string };
      if (!response.ok) throw new Error(body.detail || t("voiceprint.reprocess_failed"));
      setTrainingMessage(t("voiceprint.reprocess_summary", {
        processed: body.processed ?? 0,
        matched: body.matched ?? 0,
        fused: body.fused ?? 0,
        conflicts: body.conflicts ?? 0,
      }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("voiceprint.reprocess_failed"));
    } finally {
      setReprocessing(false);
    }
  };

  const candidates = clips.filter((clip) => clip.review_status === "candidate");
  const confirmed = clips.filter((clip) => clip.review_status === "confirmed");
  const rejected = clips.filter((clip) => clip.review_status === "rejected");

  return (
    <section className="mb-4 rounded-md border border-border bg-card/40 p-3" aria-label={t("voiceprint.title")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("voiceprint.title")}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("voiceprint.help")}
          </p>
        </div>
        <button type="button" onClick={() => void load()} className="text-[10px] text-muted-foreground hover:text-foreground">{t("voiceprint.refresh")}</button>
      </div>
      {trainingMessage && <p className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px] text-amber-200">{trainingMessage}</p>}
      <p className={`mt-2 rounded border p-2 text-[10px] ${matchingEnabled ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-200" : "border-amber-500/30 bg-amber-500/5 text-amber-200"}`}>
        {matchingEnabled ? t("voiceprint.matching_enabled") : t("voiceprint.matching_disabled")}
      </p>
      <div className="mt-2 text-[10px] text-muted-foreground">
        <span className={trainingStatus === "ready" ? "text-emerald-400" : "text-amber-300"}>
          {trainingStatus === "ready" ? t("voiceprint.training_ready") : t("voiceprint.training_not_ready")}
        </span>
        {trainingModel && <> · {t("voiceprint.training_meta", { count: trainingSampleCount, model: trainingModel })}</>}
        <span> · {t("voiceprint.quality_status", { status: t(`voiceprint.quality_${trainingQuality}`) })}</span>
      </div>
      {trainingStatus === "ready" && (
        <div className="mt-2 flex flex-wrap gap-2">
          {matchingEnabled && (
            <button type="button" onClick={() => void reprocess()} disabled={busy || reprocessing} className="text-[10px] text-accent hover:text-foreground disabled:opacity-50">
              {reprocessing ? t("voiceprint.reprocessing") : t("voiceprint.reprocess")}
            </button>
          )}
          <button type="button" onClick={() => void revoke()} disabled={busy || reprocessing} className="text-[10px] text-red-300 hover:text-red-200 disabled:opacity-50">
            {busy ? t("voiceprint.revoking") : t("voiceprint.revoke")}
          </button>
        </div>
      )}
      {loading ? <p className="py-3 text-xs text-muted-foreground">{t("voiceprint.finding")}</p> : error ? <p className="py-3 text-xs text-red-400">{error}</p> : (
        <>
          {candidates.length === 0 && confirmed.length === 0 && <p className="py-3 text-xs text-muted-foreground">{t("voiceprint.no_clips")}</p>}
          <div className="mt-2 space-y-2">
            {candidates.map((clip) => (
              <div key={clip.transcript_id} className="rounded border border-border/70 p-2">
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    aria-label={`Select voice clip from ${formatDateTime(clip.started_at)}`}
                    checked={selected.has(clip.transcript_id)}
                    onChange={(event) => setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(clip.transcript_id); else next.delete(clip.transcript_id);
                      return next;
                    })}
                    className="mt-1 accent-accent"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-medium">{clip.camera_name ?? t("voiceprint.camera")} · {formatDateTime(clip.started_at)}</div>
                    <div className="text-[10px] text-muted-foreground">{clip.duration_seconds}s · {Math.round((clip.speaker_confidence ?? 0) * 100)}% {t("voiceprint.visual_attribution")}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">{clip.attribution_reason}</div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      {t("voiceprint.quality")}: {clip.quality?.eligible ? t("voiceprint.eligible") : t("voiceprint.not_eligible", { reasons: clip.quality?.reasons.join(", ") || t("voiceprint.needs_review") })} · {t("voiceprint.source", { version: clip.attribution_model_version ?? "video-correlated-v1" })}
                    </div>
                    {clip.transcript && <div className="mt-1 text-xs text-foreground/90">“{clip.transcript}”</div>}
                    {clip.audio_available && clip.audio_url && (
                      <audio className="mt-1 h-7 w-full" controls preload="none" src={`${clip.audio_url}${token ? `?token=${encodeURIComponent(token)}` : ""}`} />
                    )}
                  </div>
                  <button type="button" onClick={() => void decide([clip.transcript_id], "reject")} disabled={busy} className="text-[10px] text-muted-foreground hover:text-foreground">{t("voiceprint.not_person")}</button>
                </div>
              </div>
            ))}
          </div>
          {candidates.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="accent-accent" />
                {t("voiceprint.consent")}
              </label>
              <button type="button" onClick={() => void decide([...selected], "confirm")} disabled={busy || selected.size === 0 || !consent} className="rounded border border-accent px-2 py-1 text-[10px] text-accent disabled:opacity-50">{t("voiceprint.confirm")}</button>
            </div>
          )}
          {confirmed.length > 0 && (
            <div className="mt-3 border-t border-border/60 pt-2">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("voiceprint.confirmed", { count: confirmed.length })}</div>
              <div className="mt-1 space-y-1">
                {confirmed.map((clip) => <div key={clip.transcript_id} className="flex items-center justify-between text-[10px] text-muted-foreground"><span>{formatDateTime(clip.started_at)} · {clip.camera_name ?? t("voiceprint.camera")}</span><button type="button" onClick={() => void decide([clip.transcript_id], "remove")} disabled={busy} className="text-muted-foreground hover:text-foreground">{t("voiceprint.remove")}</button></div>)}
              </div>
            </div>
          )}
          <label className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <input type="checkbox" checked={includeRejected} onChange={(event) => setIncludeRejected(event.target.checked)} className="accent-accent" />
            {t("voiceprint.show_rejected")}
          </label>
          {includeRejected && rejected.map((clip) => <div key={clip.transcript_id} className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground"><span>{formatDateTime(clip.started_at)} · {t("voiceprint.rejected")}</span><button type="button" onClick={() => void decide([clip.transcript_id], "reopen")} disabled={busy} className="text-accent hover:underline">{t("voiceprint.reopen")}</button></div>)}
        </>
      )}
    </section>
  );
}
